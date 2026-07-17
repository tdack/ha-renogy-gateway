---
name: renogy-debugging-playbook
description: >
  Symptom-to-cause triage playbook for the renogy_gateway Home Assistant
  integration. Use when debugging: entities unavailable or stuck "unknown",
  integration won't load, ConfigEntryNotReady/ConfigEntryAuthFailed, reauth
  loops, HTTP 401/999, RTM WebSocket 403 or connect-ack code 3/6, phantom
  tank/temp/TPMS entities, ghost slots, wrong writability in either direction
  (a Number/Select that should be a sensor, or a setting stuck read-only —
  force-readonly curation, HIDE_LEAVES, ctrl_sp_blacklist), entities lost
  after reconnect, writes that appear to
  fail (ack code 14), stale read-back, wrong or missing entity names, or
  turning on debug logging. Each symptom has discriminating experiments and
  known-trap history grounded in this repo's code and CHANGELOG.
---

# Renogy Gateway debugging playbook

A symptom→cause runbook for `custom_components/renogy_gateway/`. Every claim
here is grounded in this repo's source (paths are repo-relative); re-verify
against the file before acting — code moves. Verified against v0.5.1
(2026-07-12).

## When NOT to use this skill

- **Settled historical investigations** ("why did 0.2.x parse ops wrong?",
  full incident narratives) → `renogy-failure-archaeology`.
- **Protocol theory** (frame formats, auth flow design, schema semantics in
  the abstract) → `renogy-protocol-reference`. This playbook only quotes
  protocol facts where they discriminate between causes.
- **Building measurement/probe tooling** (HAR analysis, live probes,
  capture tooling) → `renogy-diagnostics-and-tooling`.
- **Deciding whether/how to change code** once you've found the cause →
  `renogy-change-control` (fixes usually mirror to the sibling
  `renogy-gateway` TypeScript repo, which is canonical).

## Jargon (defined once)

| Term | Meaning |
|---|---|
| **sp** | Topic path: `"<did>/<namespace>.<field_path>"`, e.g. `4623.../distribution_box.dc_10a_3.state`. `<did>` may be `1` as a gateway-local shorthand (used for `gwm.*` RPCs). |
| **did / did_str** | Device id, an int64. Always use the string form — JSON float64 parsing corrupts the last digits (`docs/PROTOCOL.md` §3). Python's `json` keeps int precision, but the *server-side* symptom (connect-ack code 3) still exists if the wrong did is sent. |
| **pid** | Product id, e.g. `000F003C` (RIV1230RCH-24S inverter). Keys the schema (`gwm.get_product`). |
| **namespace** | One schema model a device exposes, e.g. `distribution_box`, `tpms`, `charger`. A device's role IS its namespace set. |
| **leaf** | Last segment of a field path, e.g. `state` in `dc_10a_1.state`. |
| **RTM** | The real-time WebSocket at `wss://gateway.renogy.com/rtm/ws` (`api/rtm.py`). |
| **op codes** | RTM frame ops: 9/8 connect/connect-ack, 2→3 read, 4 subscribe, 7 telemetry push, 6 RPC, **1 write (real circuits)**. |
| **ops (schema)** | A field's allowed-operations list from `gwm.get_model`, e.g. `[1,2,4,5,7]`. An enum list, NOT a bitmask — see symptom F. |

## Safety fence — reproducing issues

**Read-only probes never switch circuits**: op-2 reads, op-4 subscribes,
op-6 discovery RPCs (`gwm.devs`, `gwm.get_product`, `gwm.get_model`), REST
GETs. But any *live* session runs on the owner's account and credentials —
confirm with the owner before opening one (→ `renogy-analysis-and-evidence`
Recipe 5).

**NEVER issue op-1 writes or `scene.run` against the live rig without
explicit human permission.** They switch physical circuits (lights, pumps,
inverter, refrigerator). This is a standing project rule, not a suggestion.
If a diagnosis seems to require a live write, stop and ask; usually a unit
test against `tests/` fixtures answers the same question.

## Turn on debug logging first

The manifest declares `"loggers": ["custom_components.renogy_gateway"]`
(`custom_components/renogy_gateway/manifest.json`), so HA's UI "Enable debug
logging" button on the integration works. Or in `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.renogy_gateway: debug
```

Or live, without restart:

```yaml
service: logger.set_level
data:
  custom_components.renogy_gateway: debug
```

The lines the triage sections below rely on (the full verbatim table of
every log line lives in `renogy-diagnostics-and-tooling` §1.2):

| Log line (format string) | Source | Meaning |
|---|---|---|
| `RTM connected (did=%s)` | `api/rtm.py` `connect()` | Handshake + connect-ack succeeded |
| `Discovered %d devices behind gateway %s` | `coordinator.py` `_connect_and_discover` | gwm.devs pipeline worked |
| `Initial read failed for %s` | `coordinator.py` `_read_initial` | A seed op-2 read failed for that sp |
| `RTM reconnecting in %ds` | `coordinator.py` `_reconnect_loop` | Backoff reconnect scheduled |
| `RTM reconnect attempt failed` | `coordinator.py` `_reconnect_loop` | One attempt failed; backoff doubles |
| `RTM reconnected successfully` (INFO) | `coordinator.py` | Recovery complete |
| `get_product(%s) failed` / `get_model(%s) failed` | `api/discovery.py` | Schema resolution failed for a pid/namespace |
| `gwm.devs step-1 failed; proceeding anyway` | `api/discovery.py` `_get_devices` | Gateway self-registration RPC failed |
| `Could not read userdata_str.config for %s` | `api/discovery.py` | User labels unavailable for that device |
| `Write to %s returned unexpected code: %s` (WARNING) | `coordinator.py` `async_write` | Ack was neither 0 nor 14 |

## Master triage table

| Symptom | Most likely causes (in order) | Go to |
|---|---|---|
| Integration won't load; all entities missing | Connection/RTM failure (ConfigEntryNotReady, HA retries) vs auth failure (ConfigEntryAuthFailed, reauth prompt) | A |
| HA shows "Reauthentication required" | Refresh token rotated away (401/999 on `do_refresh`), or password changed | B |
| Entities exist but stuck "unknown" | Seed read failed at startup; write-only config field never pushes | C |
| Entities "unavailable" and never recover | Reconnect loop stuck failing, or (historic) disconnect callback unwired | D |
| Tank/temp/TPMS entities for hardware that doesn't exist | Phantom-slot dropping missed (all fields writable, or seed reads failed) | E |
| Field is writable that shouldn't be (or vice versa) | ops enum misread; force-readonly curation; ctrl_sp_blacklist; HIDE_LEAVES | F |
| A device lost ALL entities after a reconnect | Zero-field rediscovery — should be caught by non-destructive merge | G |
| Write "fails" / read-back shows old value | Ack code 14 is success-queued; op-2 read-back returns stale cache | H |
| Wrong/missing entity names | userdata_str.config parse, `--` placeholder, namespace-qualified keys, curated labels | I |
| RTM connect-ack code 3 | Wrong did in op-9 (int64 precision class of bug) | A3 |
| `gwm.devs` returns code 6 | Step-1 gateway registration skipped/failed | A4 |

---

## A. Integration won't load / all entities unavailable at startup

`coordinator.py` `async_setup` maps failures onto exactly two HA outcomes:

- `RenogyConnectionError` or `RenogyRTMError` → **ConfigEntryNotReady** — HA
  retries setup automatically with backoff. Transient: network, Renogy
  outage, RTM handshake failure.
- `RenogyAuthError` → **ConfigEntryAuthFailed** — HA starts the reauth flow
  (`config_flow.py` `async_step_reauth` → `async_step_reauth_confirm`).
  Persistent: credentials/tokens dead. See symptom B.

**Discriminate:** Settings → Devices → the config entry. "Retrying setup"
message = NotReady; a reauth notification = AuthFailed. Then read the debug
log for which step died:

1. **No `RTM connected` line, error mentions WS handshake** — network or a
   403. `api/rtm.py` `_open_ws` already handles one 403 by calling
   `auth.refresh_rtm_token()` and retrying once; a second 403 raises
   `RenogyConnectionError("RTM WS retry failed: ...")`. Two 403s in a row
   usually means the stored rtm_token chain is dead → delete/re-add or
   reauth (login re-mints via `app-register`, `api/auth.py` `_app_register`).
2. **`RTM connect-ack timed out`** — WS opened but no op-8 within 10 s
   (`_CONNECT_TIMEOUT`). Usually transient; NotReady retry handles it.
3. **`RTM connect-ack failed (code 3)`** — the op-9 frame carried the
   **wrong did**. Per `docs/PROTOCOL.md` §4, code=3 with no data means the
   server didn't recognise the RTM-connect did — the classic cause is int64
   precision loss (`257470607149498369 → ...368` through float64). Python's
   `json.loads` does not lose int precision, but check: is `rtm_did` the
   RTM-connect did from `refresh-token`/`app-register` (`didStr` preferred —
   `api/auth.py` `refresh_rtm_token` does `rtm_data.get("didStr") or
   rtm_data["did"]`), not a per-device did? The two id spaces are different
   and must not be mixed (§3).
4. **Connected, but discovery returns code 6 on `gwm.devs`** — step-1
   registration was skipped or failed. `docs/PROTOCOL.md` §7.1: `1/gwm.devs`
   must be called twice — first `{dids:[<gatewayDid>]}` (registers the
   gateway into the RTM session), then `{gatewayId:<gatewayDid>}`. Skipping
   step 1 yields code=6 on step 2. `api/discovery.py` `_get_devices` does
   both, and logs `gwm.devs step-1 failed; proceeding anyway` if step 1
   errors — if you see that line followed by an empty device list, that's
   your cause.

## B. Auth failures and reauth loops

Facts from `api/auth.py` (verify there):

- **HTTP 401 AND 999 both mean stale/rejected auth.** The Renogy API returns
  the non-standard status **999** for stale access tokens
  (`docs/PROTOCOL.md` §2). `api/rest.py` `_get`/`_post` treat 401 and 999 as
  "refresh and retry once"; `_refresh_access` treats 401/999 on the refresh
  endpoint itself as fatal: `RenogyAuthError("Refresh token rejected —
  re-login required")`.
- **Refresh tokens ROTATE.** Every `do_refresh` returns a new pair and kills
  the old refresh token. The coordinator persists every rotation immediately
  via the `_persist_tokens` closure (`coordinator.py` `__init__`) into the
  **config entry data** (`CONF_ACCESS_TOKEN`, `CONF_REFRESH_TOKEN`,
  `CONF_RTM_TOKEN`, `CONF_RTM_DID`, `CONF_DEVICE_UUID`). Lock-out signature:
  something else consumed a rotation that HA never persisted — e.g.
  restoring an old HA backup, or running a second client (the sibling repo's
  dashboard/bridge, a test script) **on the same token chain**. The stored
  refresh token is then one-or-more rotations stale and dies with 401/999 →
  ConfigEntryAuthFailed → reauth. Note: each client that logs in separately
  gets its own chain; the hazard is sharing a persisted chain, not sharing
  the account.
- **RTM token endpoints** (`docs/PROTOCOL.md` §2): `POST
  /api/v2/device/refresh-token` is rotation-only and tolerates an *expired*
  prior token. Its error vocabulary discriminates misuse: `SYS003 "token can
  not null"` = you sent `{}`/`null`; 500 `SYS001` = you sent `{"token":""}`;
  `DMC400 "User data anomaly detected"` = you sent an *account*
  access/refresh token instead of an RTM token. First-ever token comes from
  `POST /api/v2/device/app-register` instead (cold-boot, §2.1) — implemented
  in `api/auth.py` `login()` → `_app_register`.
- **Reauth flow:** `config_flow.py` `async_step_reauth_confirm` does a full
  fresh login (new token chain, new app-register) and overwrites the entry's
  tokens. If reauth itself fails with `invalid_auth`, the password is wrong;
  `cannot_connect` is network/Renogy-side.

**Trap story:** login sends the password cleartext over TLS — never log
request bodies while debugging auth (`api/auth.py` docstring).

## C. Entities stuck "unknown"

An entity shows "unknown" when `_value` is None — it never got a seed value
or a push (`entity.py` reads the cached value in `async_added_to_hass` from
`coordinator.get_value`).

Mechanism (`coordinator.py` `_connect_and_discover`): at startup every
**readable** field gets one op-2 seed read under a **semaphore of 4**
(`sem_read = asyncio.Semaphore(4)`); failures are debug-logged as
`Initial read failed for %s` and silently leave the field unseeded.

Discriminate:

1. **Grep the debug log for `Initial read failed for <sp>`.** Present →
   the seed read timed out or errored under the connect-time RPC burst.
   Reload the integration; if it seeds on a quiet retry it was burst
   congestion.
2. **Is the field subscribable?** Check its schema ops. Write-only or
   read-no-subscribe config fields (charge limits, alarm thresholds) never
   push op-7 — they depend *entirely* on the seed read. For these, a failed
   seed means "unknown" until the next reload. Subscribable telemetry
   fields self-heal on their next push.
3. **Is it a phantom instance slot that escaped dropping?** See E.

## D. Entities went unavailable and never recover

Mechanism: `api/rtm.py` `_reader()` fires the unexpected-disconnect callback
from its `finally` block (unless `_closing` — an intentional `disconnect()`).
The coordinator wires that to `schedule_reconnect` (`coordinator.py`
`__init__`), which runs `_reconnect_loop`: fire availability=False, then
retry `disconnect → _connect_and_discover` with backoff doubling from
`RTM_RECONNECT_DELAY_MIN` = 2 s to `RTM_RECONNECT_DELAY_MAX` = 30 s
(`const.py`). Success fires availability=True and logs
`RTM reconnected successfully` (INFO).

Discriminate:

1. **Log shows repeating `RTM reconnecting in %ds` / `RTM reconnect attempt
   failed`** — the loop is alive but every attempt fails. Look at *why*:
   network down, Renogy outage, or a dead token chain (auth errors are
   caught in the loop and retried too — a permanently dead refresh token
   retries forever at 30 s intervals rather than triggering reauth; that is
   current behaviour, verify in `_reconnect_loop`'s except clause).
2. **Log shows NO reconnect lines at all after the drop** — the disconnect
   signal never fired. This is the **0.4.0 recurrence signature**: before
   commit `1da7fd8` ("fix(rtm): wire RTM reader disconnect to coordinator
   reconnect"), `schedule_reconnect()` existed but was never invoked — the
   reader exited silently, entities stayed "available" showing stale data
   forever, until HA reloaded the integration. If you see stale-but-
   available entities and a silent log, check that
   `set_unexpected_disconnect_callback` is wired in `coordinator.py`
   `__init__` and that `_reader`'s `finally` still calls it when not
   `_closing`.
3. **`schedule_reconnect` no-ops if `self._reconnect_task` is already set**
   — a stuck/never-cleared task blocks all future reconnects. The loop
   clears it (`self._reconnect_task = None`) only on exit; check for a
   wedged task if reconnects stop happening after an earlier recovery.

Note also: entities flip unavailable *by design* during the reconnect window
(`_fire_availability(False)`) — brief unavailability that self-heals within
~2–30 s is normal operation, not a bug.

## E. Phantom/ghost entities for tanks, temps, TPMS slots

The schema advertises **every** slot a model supports (`ai_1..N` tanks,
`temp_N` probes, `tp_state_N` TPMS positions) whether or not the rig has
that sensor wired. `coordinator.py` `_drop_phantom_instances` removes fields
for slots with no live seeded value, matching `_INSTANCE_PATTERNS`
(`^ai_\d+$`, `^temp_\d+$`, `^tp_state_\d+$`).

**The why that matters:** liveness is judged from **non-writable fields
only** — `any(not f.writable and self._last_values.get(f.sp) is not None ...)`.
Settings-type fields (calibration_pressure, alarm thresholds, axle_num)
answer with a stable firmware default even for an unbound slot, so a
writable field's default would make every unbound slot look live. Only
genuine *readings* count.

Discriminate:

1. **Ghost entities present** → either (a) every field in the slot is
   writable (nothing qualifies as a reading — the drop can't fire), or
   (b) a genuinely-unbound slot's *reading* returned a value anyway, or
   (c) the seed reads for the whole device failed so `_last_values` is
   empty... except (c) drops *real* slots too, which is the inverse symptom:
2. **Real sensor's entities missing** → its non-writable fields' seed reads
   failed at startup (`Initial read failed for %s` in the log), so the slot
   was judged phantom and dropped. Reload the integration on a quiet
   connection. Note `_drop_phantom_instances` runs once per
   `_connect_and_discover` — a reconnect re-runs it.

History: ghost TPMS/tank slots were the 0.2.5 fix ("drop ghost (unbound)
instance slots", `CHANGELOG.md`).

## F. A field is writable that shouldn't be (or vice versa)

The single biggest trap in this codebase. Layers, in evaluation order
(`api/discovery.py` `_expand_sp`):

1. **`ops` parsing (`_parse_ops`)** — schema `ops` is a **list drawn from
   the enum {1,2,4,5,7}**, not a bitmask. `5` and `7` are composite codes
   meaning "read + subscribe"; **write is contributed ONLY by the literal
   code `1`** being present in the list — never by decomposing 5 or 7.
   Naively OR-ing raw values (`mask |= 7` sets bit 0) marks every
   `[2,4,5,7]`-shaped pure reading writable. **This bit the project twice**
   (0.2.3 band-aid, 0.2.4 root-cause fix, 0.2.7 follow-up — `CHANGELOG.md`;
   full account in `docs/PROTOCOL.md` §7.4). If sensors are surfacing as
   Number/Select entities en masse, suspect this first.
2. **`HIDE_LEAVES`** (`const.py`) — protocol internals/maintenance commands
   (`save_config`, `clean_history_data`, `di_mapping`, channel-count
   bookkeeping like `dc_10a_count`, ...) are dropped entirely, not made
   read-only. A "missing" setting may be deliberately hidden here.
3. **Force-readonly curation** (`api/discovery.py` `_is_force_readonly`) —
   strips the write bit where the schema lies (`docs/PROTOCOL.md` §7.7
   documents the schema inconsistencies). Four scopes, all matched
   **case-insensitively** (the same quantity appears as `voltage` and
   `Voltage` on one device):
   - `_FORCE_READONLY_LEAVES`: global leaf names (`voltage`,
     `ac_input_voltage`, `output_watts`, ...).
   - `_FORCE_READONLY_SUFFIXES`: `_today` daily accumulators — confirmed in
     captures reporting `ops=[1,2,4,5,7]` despite being counters.
   - `_FORCE_READONLY_LEAVES_BY_NAMESPACE`: e.g. `tpms` readings
     (`pressure`, `online`, `state`) that some rigs mark writable.
   - `_FORCE_READONLY_LEAVES_BY_PID`: e.g. `000F003C` (inverter)
     `battery_type` — fixed by product, live value 14 outside the curated
     0–5 options (the 0.5.1 fix).
4. **Runtime write guards** (`coordinator.py` `async_write`) — even a
   writable field is refused if its relative path is in the device's
   `driving_mode.ctrl_sp_blacklist` (read at discovery,
   `_get_ctrl_sp_blacklist`), and the value is validated against schema
   type/min/max (`_validate_write_value`).

Discriminate: dump the field's raw schema ops (unit test against a fixture,
or a read-only `gwm.get_model` probe). Literal `1` absent → `_parse_ops` is
correct and something upstream re-added write. Literal `1` present but the
field is clearly a reading → it belongs in a force-readonly table (with
capture evidence — the evidence bar for curation changes) and the fix must
mirror the sibling repo's `packages/core/src/params.ts`.

## G. A device lost all its entities after a reconnect

A reconnect re-runs full discovery (`_reconnect_loop` →
`_connect_and_discover`). A frame lost in the connect-time RPC burst can
resolve a device to **zero fields** even after two layers of retry:
`api/rtm.py` `rpc()` retries timeouts 3× internally, and `api/discovery.py`
`_rpc_with_retry` wraps that with 3 more attempts with backoff (catching
outright `RenogyRTMError`, not just timeouts — added in 0.5.0).

The last line of defence is `coordinator.py` `_merge_devices`
(non-destructive merge, 0.5.0): if a fresh pass yields a device with no
fields but the same `pid` had fields before, **keep the prior schema** and
take only live metadata (`online`, `name`) from the fresh pass. A device
genuinely absent from the fresh list is still dropped.

So if a device's entities all vanished:

1. Was the device **absent from `gwm.devs` entirely** (removed/offline at
   the gateway)? Merge doesn't protect that — check
   `Discovered %d devices behind gateway %s` counts across reconnects.
2. Did the **pid change** between passes? The merge requires
   `prior.pid == device.pid`; a pid change discards the prior schema.
3. Was this the **first** connect (no prior to merge from)? Then it's just
   symptom A's discovery-failure case — look for `get_product(%s) failed` /
   `get_model(%s) failed`.

A zero-field rediscovery that *was* merged is invisible to users by design;
it only matters if you're wondering why entity definitions look stale after
a firmware change — reload the integration to force a clean pass.

## H. Write appears to fail / read-back shows the old value

Facts (`api/rtm.py` `write()` docstring, `docs/PROTOCOL.md` §4):

- Ack `code=0` — explicit success, data echoes the set value.
- Ack **`code=14` — accepted/queued.** The server has forwarded the command;
  the real new state arrives shortly as an **op-7 push**. This is a
  *success* code: `coordinator.py` `async_write` treats `(0, 14)` as fine
  and warns on anything else (`Write to %s returned unexpected code: %s`).
- **Do NOT op-2 read back immediately after a write** — the server returns
  stale cached data before the device propagates. Wait for the op-7 push.
  A "write didn't take" report where the entity updates a second or two
  later is this, working as designed.

Discriminate: genuine failures raise (`RenogyRTMError`/`TimeoutError`,
logged `Write to %s failed: %s`) or are blocked pre-flight by
`async_write`'s guards (blacklist, unknown sp, not writable, type/bounds) —
those surface as `HomeAssistantError` in the HA UI with a specific reason
string. An "unexpected code" warning with a code other than 0/14 is new
territory: capture it and check against the sibling repo before guessing.

**Reminder: reproducing this live means op-1 writes — explicit human
permission first.**

## I. Wrong or missing entity names

Name resolution order (see `api/discovery.py` `_get_user_labels` /
`_apply_labels`, and `api/labels.py` for curated fallbacks):

1. **User-assigned labels** from `<did>/userdata_str.config` (op-2 read).
   Traps, all confirmed against real captures (`docs/PROTOCOL.md` §5):
   - The payload is a JSON-encoded string, **sometimes double-encoded** —
     `_get_user_labels` parses up to twice.
   - Keys are **namespace-qualified** (`"distribution_box.dc_10a_1"`), not
     bare channel keys — the namespace prefix is stripped before matching.
   - Values are objects; the name is `value.name`. An **unset name reads
     back as the placeholder `"--"`** — treated as absent (schema default
     wins), never shown literally.
   - The label applies to *all* co-channel fields sharing the
     `channel_key` (state, power, ratio, current...).
2. **Curated English labels/options** (`api/labels.py`, ported in 0.5.0)
   — schema `text`/`desc` are often Chinese; curation covers known fields.
3. **Schema-derived default** otherwise.

Discriminate:

- **All names are raw field keys** → labels never fetched. Check the log for
  `Could not read userdata_str.config for %s`, and confirm the device's
  namespace list actually includes `userdata_str` (labels are only fetched
  when it does — `_resolve_device`).
- **Names fetched but not applied** → the **0.2.9 recurrence signature**:
  that release fixed "user-assigned channel labels never being applied to
  entities" (`CHANGELOG.md`) — the fetch worked, the wiring to entities
  didn't. Verify `_apply_labels` is called and `FieldSpec.user_label` flows
  into `display_name` (`api/models.py`).
- **A channel literally named `--`** → placeholder handling regressed.
- **Chinese labels/options showing** → curation gap in `api/labels.py`;
  fix mirrors the sibling repo's curation (see
  `renogy-curation-and-flags` / `renogy-curation-parity-campaign`).

## Cross-references

- Historical root-cause narratives: `renogy-failure-archaeology`.
- Protocol spec detail: `renogy-protocol-reference` and `docs/PROTOCOL.md`.
- Curation tables and force-readonly policy: `renogy-curation-and-flags`.
- Making the fix (two-repo mirroring, evidence bar): `renogy-change-control`.
- Running tests / environment: `renogy-build-and-env`,
  `renogy-validation-and-qa`.

## Provenance and maintenance

Verified 2026-07-12 against v0.5.1. Re-verify volatile facts before trusting:

- Error mapping in setup: `grep -n "ConfigEntryNotReady\|ConfigEntryAuthFailed" custom_components/renogy_gateway/coordinator.py`
- 401/999 handling: `grep -n "999" custom_components/renogy_gateway/api/*.py`
- Reconnect backoff constants: `grep -n "RTM_RECONNECT" custom_components/renogy_gateway/const.py`
- Disconnect wiring (0.4.0 regression check): `grep -n "set_unexpected_disconnect_callback\|_on_unexpected_disconnect" custom_components/renogy_gateway/coordinator.py custom_components/renogy_gateway/api/rtm.py`
- ops parsing rules: `grep -n -A 20 "_parse_ops" custom_components/renogy_gateway/api/discovery.py`
- Force-readonly tables: `grep -n "_FORCE_READONLY" custom_components/renogy_gateway/api/discovery.py`
- Phantom-slot patterns: `grep -n -A 6 "_INSTANCE_PATTERNS" custom_components/renogy_gateway/coordinator.py`
- Write ack codes: `grep -n "code=14\|(0, 14)" custom_components/renogy_gateway/api/rtm.py custom_components/renogy_gateway/coordinator.py`
- Log format strings quoted above: `grep -rn "Initial read failed\|RTM reconnecting\|reconnected successfully" custom_components/renogy_gateway/`
- Incident history: `git log --oneline -- custom_components/renogy_gateway/api/rtm.py` and `CHANGELOG.md` (0.2.4/0.2.7 ops, 0.2.5 ghosts, 0.2.9 labels, 0.4.0 reconnect, 0.5.0 merge/retry, 0.5.1 battery_type).
