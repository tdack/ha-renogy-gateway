---
name: renogy-failure-archaeology
description: >
  The chronicle of every major investigation, dead end, rejected fix, and
  workaround-later-removed in the renogy_gateway HA integration and its
  canonical sibling repo (renogy-gateway TS monorepo). Load this BEFORE
  re-deriving any protocol behaviour, when investigating a bug whose symptom
  looks familiar (fields wrongly writable, phantom devices, entities stuck
  Unknown, stale data after disconnect, labels not applying, DID mismatches,
  scale-off-by-1000 values, CI failures on tags), or whenever you suspect a
  question might be a settled battle. Each entry is SYMPTOM -> ROOT CAUSE ->
  EVIDENCE -> STATUS with commit hashes and where the durable guard now lives.
---

# Renogy failure archaeology

Date-stamped 2026-07-12. Everything below was verified against `git log` /
`git show` in one or both repos on that date. Re-verify hashes before citing
them onward (see "Provenance and maintenance").

Two repos share this history:

- **This repo** (`ha-renogy-gateway`) — the HA HACS integration, code in
  `custom_components/renogy_gateway/`, releases chronicled in `CHANGELOG.md`
  (0.2.0 -> 0.5.1, June–July 2026).
- **Sibling** (`../renogy-gateway`, read-only, canonical) — the TS monorepo
  the integration was ported from. Its git history carries the original
  investigations; several fixes flowed in BOTH directions. Its
  `docs/PROTOCOL.md` (mirrored here as `docs/PROTOCOL.md`) is the protocol
  source of truth, and its `captures/` HARs are the evidence bar — but they
  contain credentials; never quote tokens or credentials from them.

**Rule of engagement:** before "fixing" anything that resembles an entry
below, read that entry's evidence. Several of these battles were fought
twice because a symptom recurred and the interim band-aid looked like the
fix. And never live-write-test against the real rig without explicit user
permission — `write` switches physical circuits.

## When NOT to use this skill

- **Live triage of a currently-broken system** (logs, reconnects, what to
  check first) -> `renogy-debugging-playbook`.
- **Current curation state** (which fields are hidden/renamed/read-only
  today, parity between repos) -> `renogy-curation-and-flags` and
  `renogy-curation-parity-campaign`.
- **What the protocol IS** (frames, ops, endpoints) -> `renogy-protocol-reference`
  and `docs/PROTOCOL.md`. This skill records how we *learned* it, and which
  plausible readings of it are wrong.

---

## 1. The ops-enum misparse — the single most expensive trap

**SYMPTOM:** genuine read-only telemetry (TPMS tyre pressure, shunt SOC,
inverter AC input readings, `Bat_Chg_Energy`) surfaced as editable
Configuration entities (`number`) in HA — i.e. the UI offered to *write* to
sensor readings.

**ROOT CAUSE:** `ops` in the `gwm.get_model` schema is a small **enum**
`{1,2,4,5,7}`, not a freely OR-able bitmask. `5` and `7` mean
"read + subscribe" and do **not** imply write on their own, despite
decomposing to include bit 0 in binary. `_parse_ops` OR'd raw integers as a
generic bitmask, so any field advertising `[2,4,5,7]` (no literal `1`) was
misread as writable. Writability fires **only** from a literal `1` entry.

**This bit the project TWICE:**

1. First pass (0.2.4, commit `831cd77`, 2026-06-25) special-cased the value
   `5` only.
2. `7` in a list still leaked the write bit via `mask |= 7` — exactly what
   the inverter's `Bat_Chg_Energy` / AC-input readings report. Fixed in
   0.2.7 (commit `b1d260e`, 2026-06-27): `5` and `7` both get
   "read+subscribe, write only from a separate literal 1", for bare-int and
   list forms.

**The interim band-aid, later removed:** 0.2.3 (commit `4108f95`) forced a
hardcoded list of "well-known telemetry" path patterns read-only (ported
from the sibling's `apps/hass-bridge/src/filter.ts` — a tool built for MQTT
publish filtering, not classification). 0.2.4 (`831cd77`) found the real bug
by re-reading the sibling's `packages/core/src/discovery.ts` `opsToCaps` and
**deleted the path-pattern override entirely**. Do not reintroduce
path-pattern allowlists for writability; parse ops correctly instead.

**EVIDENCE:** `docs/PROTOCOL.md` §7.4 (the `Bat_Chg_Energy` vs
`dc_output_ext.state` contrast) and §7.7; sibling doc commit `626c809`
("ops is a small enum ... bit the ha-renogy-gateway port twice"). Confirmed
against real RTM captures in the sibling's `captures/*.har`.

**GUARDS:** `custom_components/renogy_gateway/api/discovery.py` `_parse_ops`;
`tests/test_discovery.py`; PROTOCOL.md §7.4/§7.7.

**STATUS: settled.** If a field looks writable and shouldn't be, suspect a
schema lie (entry 2), not the ops parser.

---

## 2. Schema lies — the firmware's schema is not truth

The `get_model` schema genuinely mislabels fields. Catalogue in
`docs/PROTOCOL.md` §7.7. Distinct confirmed lies:

- **`_today` accumulators carry a real write bit.** Every lowercase
  `_today` daily counter in `inverter_history` (`bat_chg_ah_today`,
  `generat_energy_today`, ...) reports `ops=[1,2,4,5,7]` — literal `1`
  genuinely present despite being a counter. Suffix-based force-readonly
  override added in 0.2.7 (`b1d260e`): `_FORCE_READONLY_SUFFIXES =
  ("_today",)` in `api/discovery.py`.
- **TPMS readings marked writable on some rigs.** `tpms.tp_state_N.pressure`,
  `.online`, and the tyre-status enum `.state` report full `ops=7` on the
  real rig — so the ops fix alone didn't cover them. Namespace-scoped
  override (`_FORCE_READONLY_LEAVES_BY_NAMESPACE`) added in 0.2.5
  (`b575517`) — namespace-scoped deliberately, because bare `state` IS the
  genuine writable on/off control on `distribution_box` channels.
- **Case-inconsistent leaf names on the same device** (lowercase `voltage`
  alongside `battery_input.Voltage`) -> force-readonly leaf checks made
  case-insensitive in 0.2.7 (`b1d260e`).
- **Chinese units:** `charger.max_current` reports unit `安培` (Chinese for
  Ampere) on this rig. Translation added to `_UNIT_MAP` in 0.2.8
  (`fcfceb4`), matching the sibling's `packages/core/src/params.ts`.
- **Identically-named fields disagree on writability across devices:**
  `start_battery.desired_voltage/desired_current` report `ops=[2,4,5,7]`
  (read-only) while `charger.desired_voltage/desired_current` are writable.
  **Deliberately NOT "fixed"** (0.2.8, `fcfceb4`): forcing them writable
  risks a write the firmware silently rejects; narrow, low-impact gap
  (DC-DC starter-battery charge profile only). Do not re-open unasked.

The sibling ported these guards back as `isForceReadonly` in
`packages/core/src/discovery.ts` (commit `84856f2`, 2026-06-28) so the
dashboard and hass-bridge share the correction at the source.

**GUARDS:** `api/discovery.py` `_FORCE_READONLY_LEAVES` /
`_FORCE_READONLY_SUFFIXES` / `_FORCE_READONLY_LEAVES_BY_NAMESPACE`;
`tests/test_discovery.py`; PROTOCOL.md §7.7.

**STATUS: settled** (catalogue is monitored — new rigs may add lies; add to
the tables and §7.7, never weaken `_parse_ops`).

---

## 3. int64 DID precision loss through JSON parse

**SYMPTOM:** RTM connect-ack `code=3` with no data ("wrong DID"); `gwm.devs`
returns `code=6`; operations silently target a device that doesn't exist.

**ROOT CAUSE:** `did` fields are int64 JSON numbers. Any float64 JSON parse
(JavaScript `JSON.parse`, and equivalent float round-trips in Python)
corrupts the low digits: `4623589794012005944 -> 4623589794012006000`;
`257470607149498369 -> 257470607149498368`.

**RULE:** always use `did_str`. In float64 JSON parsers (the TS reference),
extract a numeric `did` by regex from the raw text **before** `JSON.parse` —
PROTOCOL.md documents that discipline for JS. The HA port does not need the
regex: Python ints are lossless, so `api/auth.py` simply `json.loads()`es
the response text and prefers `didStr` over the numeric `did`
(`refresh_rtm_token`, ~line 218). Scene objects carry the same hazard: `id`,
`gatewayDeviceId`, `userId`, `deviceId` are int64 (PROTOCOL.md §8.1).

**Sibling war story:** the TS BigInt-safe JSON layer itself had a bug — the
BigInt tag marker contained literal NUL bytes, which `JSON.parse` rejects
("Bad control character in string literal"); that, not malformed server
data, was the real cause of scene-load failures (sibling commit `ae84784`,
2026-06-13). Moral: when scene JSON "won't parse", check your own int64
plumbing before blaming Renogy.

**EVIDENCE:** PROTOCOL.md §3 (did_str rule + examples), §4 (connect-ack
code=3), §7.1 (gwm.devs int64 warning), §8.1 (scene ids); sibling commits
`1a3fc1c` (BigInt-safe JSON), `ae84784` (NUL-byte fix).

**STATUS: settled.** Any new endpoint returning ids: assume int64, use the
string form or raw-text extraction.

---

## 4. Reconnect never firing — dropped WS permanent until reload

**SYMPTOM:** after the RTM WebSocket dropped, entities stayed "available"
forever showing stale data; only a full integration reload recovered.

**ROOT CAUSE:** `schedule_reconnect()` existed on the coordinator but was
**never invoked** — the RTM reader task exiting unexpectedly notified
nothing. Classic orphaned-handler bug.

**FIX:** 0.4.0, commit `1da7fd8` (2026-06-28) — an unexpected-disconnect
callback fired from `_reader()`'s `finally` block, suppressed during an
intentional `disconnect()` via a `_closing` flag, wired to the coordinator's
reconnect scheduling.

**GUARDS:** `api/rtm.py` (callback + `_closing` flag), `coordinator.py`;
regression tests in `tests/test_rtm.py` and `tests/test_coordinator.py`
added in the same commit.

**STATUS: settled.** If stale-data-after-drop recurs, check the callback
wiring first, not the reconnect logic itself.

---

## 5. Ghost/phantom instance slots — and the liveness refinement

**SYMPTOM:** `tp_state_3..10` (tyre slots with no physical TPMS sensor
paired) appeared with every entity stuck on "Unknown". Same class of problem
for unwired tank/temp-probe slots.

**ROOT CAUSE:** the schema advertises every multi-instance slot a *model*
supports, regardless of what this rig has wired. First fix (0.2.5,
`b575517`) dropped slots with no seeded value — but the liveness test used
*any* field, and **writable settings fields (calibration_pressure, alarm
thresholds, axle_num) answer with a stable firmware default even on an
unbound slot**. Hence the refinement in the same commit: judge liveness from
**non-writable (genuine reading) fields only**.

**GUARDS:** `coordinator.py` `_drop_phantom_instances` — its docstring
states the non-writable-only rule explicitly; `tests/test_coordinator.py`.
The sibling's equivalent gating is `filterConfiguredParams`
(sibling commit `eddaf8e`).

**STATUS: settled.** Do not "simplify" the liveness check back to
any-field-seeded.

---

## 6. TPMS pressure/online/state misclassification

**SYMPTOM:** tyre pressure showed as an editable Number; the tyre-status
enum misclassified.

**ROOT CAUSE + FIX:** the schema-lie half of 0.2.5 (`b575517`) — see entry 2
(TPMS bullet). Kept as its own line because it was the concrete regression
proving the ops fix (entry 1) was necessary but not sufficient, which forced
the namespace-scoped override design.

**STATUS: settled.** Covered by `_FORCE_READONLY_LEAVES_BY_NAMESPACE` +
`tests/test_discovery.py`.

---

## 7. User channel labels never applied

**SYMPTOM:** user-configured names ("Bedroom Light" for `dc_10a_1`) never
appeared on any entity — silently, in production, always.

**ROOT CAUSE:** `_get_user_labels` implemented PROTOCOL.md's *prose*
description of `userdata_str.config` (a flat `{channel: label}` string map)
and filtered for `isinstance(v, str)`. The **real** shape, confirmed by
capture, is namespace-qualified keys with object values:
`{"distribution_box.dc_10a_1": {"name": "Bedroom Light", "channelEnable":
true, "controlMode": 0, "icon": ...}, ...}`, arriving double-encoded (JSON
string inside JSON), with unset names as the literal placeholder `"--"`.
The string filter matched nothing, ever, so the function returned `{}`.

**FIX:** 0.2.9, commit `a6b0e7f` (2026-06-27) — strip the `<namespace>.`
prefix, pull `value["name"]`, treat `"--"` as unset. The sibling documented
the real shape in PROTOCOL.md §5/§7.5 via commit `626c809` ("a port that
took the doc at face value would silently apply zero channel labels, ever").

**GUARDS:** `api/discovery.py` `_get_user_labels`; `tests/test_discovery.py`;
PROTOCOL.md §5.

**STATUS: settled.** Lesson: docs describe; captures decide. Verify payload
shapes against a HAR before coding to prose.

---

## 8. battery_type writable on inverter pid 000F003C — pid-scoped readonly

**SYMPTOM:** the RIV1230RCH-24S inverter surfaced `charger.battery_type` as
a writable `select` with impossible options — it reports `battery_type=14`,
but the curated options map only covers codes 0–5 (built for the genuine
MPPT/DC-DC chargers), and the schema's own `desc` says battery type on
REGO-family inverters is fixed by the product.

**FIX:** 0.5.1, commit `ae59831` (2026-07-05) — a **pid-scoped**
force-readonly table (`_FORCE_READONLY_LEAVES_BY_PID`, keyed `"000F003C"`),
with `pid` threaded through `_get_fields`/`_expand_sp`. Sibling equivalent:
commit `ffac2f3` (pid-scoped exclusion in `buildParams`,
`packages/core/src/params.ts`; its message says "must match the equivalent
fix in ha-renogy-gateway"). The two must stay in parity.

**GUARDS:** `api/discovery.py` `_FORCE_READONLY_LEAVES_BY_PID`;
`tests/test_discovery.py`; PROTOCOL.md §7.7 (cross-product-type
inconsistency note added by `ffac2f3`).

**STATUS: settled.** Pattern to reuse: when a lie is product-specific, scope
the override by pid, not globally.

---

## 9. Discovery RPC frame drops -> schema-less devices, entity teardown

**SYMPTOM:** after (re)connect, some devices resolved with no schema at all
— a different subset each run — with no recovery; and a rediscovery after an
auto-reconnect could resolve a device to zero fields and tear down all its
entities.

**ROOT CAUSE:** `get_product`/`get_model`/`gwm.devs` frames get dropped
under the concurrent connect-time burst. A drop surfaces as an RTM error,
not just a timeout, which the RPC layer's own retry didn't cover. And the
coordinator replaced devices wholesale on rediscovery.

**FIX (0.5.0, 2026-06-28):**
- `c7d9f77` — backoff-retry wrapper around the discovery RPCs (mirroring the
  sibling's `withRetry` in `packages/core/src/discovery.ts`, itself from
  sibling commit `5259d00`, which also bounded in-flight RPCs at 4), plus
  surfacing the gateway itself as a device from the `gwm.devs` step-1
  registration response (deduped by `did_str`) so the ONE Core resolves as
  a device alongside its children.
- `7337639` — non-destructive merge on rediscovery: pid unchanged but fresh
  fields empty => keep prior fields, refresh only live metadata (online,
  name); genuinely absent devices still drop. Mirrors the sibling's
  `_runLive` merge.
- `bde62a4` — dedupe concurrent `get_model` RPCs. (This one shipped
  earlier, in **v0.4.0** — verified via `git tag --contains bde62a4`; same
  2026-06-28 date, different release.)

**GUARDS:** `api/discovery.py` retry wrapper + gateway-as-device;
`coordinator.py` merge; `tests/test_discovery.py`, `tests/test_coordinator.py`.

**STATUS: settled.** "Device lost all its entities after a blip" should
never recur; if it does, check the merge path before the network.

---

## 10. Credentials in storage — password persisted, email in diagnostics

- **Password persisted cleartext** in the config entry (`.storage`) on setup
  and reauth — and never read back (login only ever uses freshly entered
  credentials). Removed from both write paths with a v1->v2 config-entry
  migration stripping existing installs: 0.4.0, commit `7a864fa`
  (2026-06-28). Guards: `config_flow.py`, `__init__.py` migration,
  `tests/test_config_flow.py`, `tests/test_init.py`.
- **Account email leaked into user-downloadable diagnostics** — added to the
  redaction set alongside the existing token redaction: commit `73ee0a6`.
  Guards: `diagnostics.py`, `tests/test_diagnostics.py`.

**STATUS: settled.** Any new persisted field or diagnostics key: check it
against these two commits' intent first.

---

## 11. CI Validate failing on tag pushes — GitHub API ref propagation race

**SYMPTOM:** the hacs/action Validate workflow failed on a freshly-pushed
tag even though the identical commit had just passed on the main-branch
push.

**ROOT CAUSE:** hacs/action resolves the manifest via the GitHub API using
the pushed ref; on a fresh tag the API hasn't replicated it yet, so the
manifest fetch returns None. Not a code problem at all.

**FIX:** commit `8db60f6` — don't run Validate on tag pushes
(`.github/workflows/validate.yml`).

**STATUS: settled.** Do not "fix" a red tag-push Validate by touching the
manifest.

---

## 12. Python 3.13-incompatible except clauses; CI pinned to wrong Python

**SYMPTOM:** the integration was a `SyntaxError` on any real HA install,
while CI stayed green.

**ROOT CAUSE:** `except A, B:` (unparenthesised) only parses under PEP 758
(Python 3.14+); HA's stable runtime is 3.13. CI had pinned setup-python to
3.14, so it never caught it.

**FIX:** commit `f3580cf` (2026-06-25) — parenthesised the tuples and pinned
CI to 3.13 (`.github/workflows/test.yml`).

**STATUS: settled.** Keep CI's Python matched to HA's actual runtime, not
the newest available.

---

## 13. Deprecated asyncio.get_event_loop in the RPC path

**SYMPTOM:** 3.12+ deprecation warning from `RenogyRTM._call()`.

**FIX:** swapped to `asyncio.get_running_loop()` — folded into `1da7fd8`
(0.4.0) alongside the reconnect fix.

**STATUS: settled.** Trivial; listed so nobody hunts for a separate commit.

---

## 14. The RTM first-token bootstrap saga — do not re-fight

**QUESTION:** how does a never-registered client mint its *first* rtmToken?
(Everything else rotates an existing one via `refresh-token`.)

**THE DEAD END (sibling, 2026-06-12):** a systematic probe of
`refresh-token` body variants (sibling commit `86eeeed`,
`scripts/probe-rtm-bootstrap.ts`) proved refresh-token is **rotation-only**:
`""` -> 500 `SYS001`; `{}`/`null` -> `SYS003`; account tokens -> `DMC400`.
An intermediate capture analysis (sibling `e86dff0`) also corrected the
token lifetime: rtmTokens live ~7 days (not ~2082), but rotation works even
on a token weeks past expiry, so a token self-renews indefinitely — and
flagged that the "fresh install" HAR wasn't a true cold boot (the keychain
had preserved device_uuid + token).

**THE ANSWER (sibling commit `00caba3`, 2026-06-12, from a genuine cold-boot
HAR):** `POST /api/v2/device/app-register` with
`{pid:"003F0000", sn:"<device_uuid>#<email>", nodeType:4}` plus the account
`x-token` -> `{did, didStr, token}`. Onboarding therefore needs only
email + password; no seed token.

**Also settled in the same era:** RTM WS-upgrade auth is a `device-token`
HTTP header carrying the rtmToken JWT — **not** the SERVERID cookie (sibling
doc commit `323de3b`); and treat HTTP 401 **and 999** as refresh triggers
(sibling commit `6fea2ac`).

**EVIDENCE:** PROTOCOL.md §2.1 ("First-token bootstrap — [SOLVED 06-12]");
sibling CLAUDE.md "Open/untested" section; `api/auth.py` implements
app-register-when-no-stored-token.

**STATUS: settled.** Anyone proposing to probe `refresh-token` bootstrap
variants again is re-running `86eeeed`. Point them at §2.1.

---

## 15. Milli-unit scaling family — HA-side and sibling-side, parity-relevant

**SYMPTOM (HA, 0.2.6):** an inverter's AC input current displayed as
"1399.98999 mA" instead of "1.40 A"; `boost_voltage` as "14.349999".

**ROOT CAUSE:** milli-prefixed schema units (mA/mV/mW) genuinely carry
milli-scale wire values (capture-confirmed: `ac_output.Output_Current =
1100`, only sensible as 1.1 A); nothing normalised them, and float noise
leaked into display.

**FIX (HA):** commit `4ae1191` (0.2.6, 2026-06-27) — `_UNIT_MAP` carries a
scale factor per unit (mA/mV/mW -> A/V/W at 0.001), applied on read for
Sensor and Number, **inverted on write** (the RTM wire value must be in the
raw unit), Number min/max scaled with the value, display precision capped.
Guards: `sensor.py`, `number.py`, `tests/test_sensor.py`,
`tests/test_number.py`.

**Sibling-side follow-ons (sibling commits, parity-relevant here):**
- `c0be656` (2026-06-28) — core normalises mV/mA/mW to base units
  (`UNIT_PREFIX_SCALE`, `unitScale` on ResolvedField): decode multiplies,
  `encodeWrite` divides back to wire scale; independent of `coef`, which
  stays unapplied.
- `30d3d9d` (2026-06-30) — min/max bounds scaled by the same factor so they
  match normalised values; made the contract explicit (validate in display
  units first, encode to wire scale last); SCHEMA_VERSION bumped to
  invalidate wire-scale cached bounds. Its message explicitly cites bringing
  core in line with this repo's `number.py` bound scaling.
- `0d245da` (2026-07-11) — the trap's third appearance: the dashboard's
  telemetry-history sampler read raw RTM frames without going through
  `SystemModel.decode()`, so `charger.charging_current` (schema unit "mA"
  on the RCC60REGO/RBC50D1S chargers) landed in the history store 1000x too
  large while its axis was labelled correctly. `buildHistoryMetrics` now
  carries `unitScale` so the sampler rescales itself.

**STATUS: settled in both repos, but MONITORED** — this bug family recurs
whenever any new code path reads raw wire values without the decode layer.
Any new consumer of raw RTM frames must apply unit scaling explicitly.

---

## Cross-cutting lessons (why these battles were lost the first time)

1. **Captures over prose.** Entries 1, 2, 7, 14 were caused or resolved by
   checking `captures/*.har` against assumptions. The sibling's captures are
   the evidence bar; the docs were corrected *from* them (`626c809`).
2. **Band-aids masquerade as fixes.** 0.2.3's path-pattern override
   (entry 1) worked, shipped, and was wrong. When a fix is a lookup table of
   symptoms, keep digging.
3. **The schema lies, but in bounded, cataloguable ways.** Force-readonly
   tables (global leaf / suffix / namespace-scoped / pid-scoped) are the
   sanctioned mechanism — scoped as narrowly as the lie.
4. **Every raw-wire consumer re-inherits the scaling bug** (entry 15, three
   times across two repos). Route reads through the decode layer or carry
   `unitScale`.
5. **int64s corrupt silently** (entry 3). String forms or raw-text
   extraction, always.
6. **Fixes flow both ways, but the sibling is canonical.** When patching one
   repo, check whether the twin needs it (`ae59831` <-> `ffac2f3`,
   `4ae1191` <-> `c0be656`/`30d3d9d`, this repo's overrides -> `84856f2`).

## Provenance and maintenance

- Verify any hash before citing: `git show --stat <hash>` from the repo
  root, and `git -C ../renogy-gateway show --stat <hash>` for the sibling.
- Cross-check release framing against `CHANGELOG.md` (this repo) and section
  numbers against `docs/PROTOCOL.md` (§2.1, §3, §5, §7.4, §7.7, §8.1) —
  numbering may drift as the doc grows.
- Confirm guard constants still exist:
  `grep -n "_FORCE_READONLY" custom_components/renogy_gateway/api/discovery.py`
  and the `_drop_phantom_instances` docstring in
  `custom_components/renogy_gateway/coordinator.py`.
- When a new investigation settles, append an entry in the same
  SYMPTOM -> ROOT CAUSE -> EVIDENCE -> STATUS shape, with hashes you have
  actually run `git show` on, and re-date the top of this file.
- All entries above verified 2026-07-12 via `git show` in both repos.
