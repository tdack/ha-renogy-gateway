---
name: renogy-architecture-contract
description: >-
  Load-bearing design decisions, invariants, and known weak points of the
  renogy_gateway HA integration. Load BEFORE any structural change: adding or
  modifying a platform/entity type, touching the coordinator or the api/ layer
  boundary, changing discovery, reconnect, token, or write paths, adding
  support for a new or rewired device model (discovery must handle it with
  zero code edits) — and
  especially whenever you are tempted to hardcode device knowledge (SKU
  tables, channel lists, controllable allowlists). Explains WHY each rule
  exists so you don't "fix" it away.
---

# Renogy Gateway — architecture contract

The rules below were each bought with a real bug or a real capture. Verify a
rule still holds before relying on it (commands at the end), but do not relax
one without evidence and a mirrored change in the sibling repo (see
`renogy-change-control`).

## When NOT to use this skill

- Wire-level protocol detail (frame shapes, auth endpoints, op codes, §-references) → `renogy-protocol-reference` and `docs/PROTOCOL.md`.
- Which specific leaves/namespaces are hidden, force-readonly, labelled, or curated, and the evidence behind each → `renogy-curation-and-flags`.
- Keeping curation in step with the sibling TS repo → `renogy-curation-parity-campaign`.
- Running tests / environment setup → `renogy-build-and-env`, `renogy-validation-and-qa`.

## Jargon (defined once)

- **sp** — topic path: `<did>/<namespace>.<field_path>`, e.g. `4623589794012005944/distribution_box.dc_10a_1.state`. The universal key for read/write/subscribe.
- **did / did_str** — device ID, an int64. `did_str` is its string form; used everywhere because JSON float64 corrupts int64s.
- **pid** — product ID string (e.g. `000F003C`), keys `gwm.get_product`.
- **namespace** — a schema model a device exposes (e.g. `distribution_box`, `charger`), keys `gwm.get_model`.
- **RTM** — Renogy's real-time WebSocket protocol (`api/rtm.py`): op 9/8 connect, op 2→3 read, op 4 subscribe, op 7 telemetry push, op 6 RPC, **op 1 write (real circuits)**.
- **Coordinator** — `RenogyCoordinator` in `coordinator.py`. NOT a HA `DataUpdateCoordinator` — see below.
- **Config entry** — HA's persisted per-account/per-gateway record; here it also stores the rotating token set.

## Control safety (read this first)

**Never test writes (RTM op 1 or `scene.run`) against the live rig without
explicit human permission.** They switch physical circuits in the owner's
home. This applies to debugging, "just checking", and automated tests alike.
All control paths in code route through `coordinator.async_write` /
`async_run_scene` — keep it that way, and keep the validation there intact.

## Layer contract

`custom_components/renogy_gateway/api/` is pure protocol; the HA layer above
consumes it only via `RenogyCoordinator`.

- **api/ has zero `homeassistant` imports** (verified 2026-07-12 by grep — see Provenance). `auth.py`, `rest.py`, `rtm.py`, `discovery.py`, `labels.py`, `models.py` depend on `aiohttp` + stdlib only.
- **One honest exception:** `api/discovery.py` imports `HIDE_LEAVES` from `..const` — a curation constant living in the HA-layer package. `const.py` itself imports nothing from HA, so the layer stays HA-free, but the import direction is a wart: don't add more upward imports; if you touch it, prefer moving shared curation constants down into `api/`.
- Two small deliberate leaks the other way: `rest.py` calls `self._auth._headers()` (marked `noqa: SLF001`), and `coordinator.py` imports HA exceptions lazily inside functions (`noqa: PLC0415`) so `_validate_write_value` stays importable without a running HA.
- The HA layer (`coordinator.py`, `entity.py`, seven platform files, `config_flow.py`, `diagnostics.py`, `__init__.py`) never talks to `RenogyRTM`/`RenogyREST` directly except through the coordinator — with one exception: `config_flow.py` constructs its own `RenogyAuth`/`RenogyREST` for login and gateway listing, using a throwaway persist callback.

### Data flow (text diagram)

```
config_flow (login → app-register → getUserGateways → pick gateway)
    └─ creates config entry: email, gateway_id/name, full TokenSet (no password)

__init__.async_setup_entry
    └─ RenogyCoordinator(hass, entry)
        └─ async_setup
            ├─ restore TokenSet from entry.data (auth.set_tokens)
            └─ _connect_and_discover
                ├─ rtm.connect (rotate rtmToken → WS upgrade w/ device-token
                │   header → op-9/op-8 handshake; one retry on 403)
                ├─ set_telemetry_dispatcher(_dispatch_telemetry)
                ├─ discovery.discover(gateway_id)  → _merge_devices (non-destructive)
                ├─ seed reads: op-2 every readable field (semaphore 4) → _last_values
                ├─ _drop_phantom_instances (judged from non-writable fields only)
                ├─ subscribe every subscribable field (op-4, semaphore 4)
                └─ _refresh_scenes (REST, best-effort — failure never blocks startup)
    ├─ explicit device_registry registration (covers zero-entity devices, e.g. Vision)
    └─ forward to platforms: binary_sensor, button, light, number, select, sensor, switch

telemetry: op-7 push → rtm._dispatch → coordinator._dispatch_telemetry(sp, value)
    → _last_values[sp] = value → per-sp entity callbacks → async_write_ha_state

availability: rtm reader exits unexpectedly → schedule_reconnect
    → _fire_availability(False) → every entity flips unavailable
    → backoff loop → _connect_and_discover → _fire_availability(True)

control: entity → coordinator.async_write (blacklist/existence/writability/
    type/bounds checks) → rtm.write op-1 → ack code 0 (ok) or 14 (queued,
    confirmation arrives as an op-7 push)
```

## The coordinator is push-based, not a DataUpdateCoordinator

`manifest.json` declares `iot_class: cloud_push`. There is no polling
interval and no `_async_update_data`: telemetry arrives as op-7 pushes over
one long-lived WebSocket. Consequences for entity code:

- `RenogyBaseEntity` (`entity.py`) extends plain `Entity` with `_attr_should_poll = False`, registers a per-sp telemetry callback and an availability callback in `async_added_to_hass`, and unregisters both on removal. New platforms MUST follow this pattern — do not reach for `CoordinatorEntity`.
- On add, an entity seeds itself from `coordinator.get_value(sp)` (the `_last_values` cache filled by the connect-time seed reads) so it shows a value immediately instead of waiting for the next push. `switch`/`light` additionally fall back to `RestoreEntity` state.
- Multi-field entities register extra callbacks themselves (see `RenogyLight`'s ratio subscription) and must unregister them too.
- `RenogySceneEntity` is the parallel base for scene button/switch entities — keyed by scene id, driven by scene callbacks + availability, not by an sp.

## Invariants

### 1. Discovery over hardcoding
Roles, capabilities, units, bounds, enums, and dimmability come from the
runtime schema (`gwm.devs` → `gwm.get_product(pid)` → `gwm.get_model(namespace)`,
with `inherit`/`ref` resolution — `api/discovery.py`). Friendly names come
from `userdata_str.config` (double-encoded JSON, `{"<ns>.<channel>": {"name": ...}}`,
`"--"` means unset). There are **no** SKU-prefix role tables, channel-name
tables, or controllable allowlists — a rewired or unfamiliar rig must work
with zero code edits. Dimmable-vs-switch is derived structurally: a writable
bool `.state` with a writable `.ratio` sibling is a light; otherwise a switch.

The **sanctioned exception** is evidence-backed curation constants
(`HIDE_LEAVES`, `_SKIP_NAMESPACES`, `_FORCE_READONLY_*`, `LABELS`,
`CURATED_OPTIONS`, `ZH_OPTION`, `_DIAGNOSTIC_PATTERNS`). Each exists because
a capture or live observation proved the schema wrong or unhelpful; each must
cite that evidence and be mirrored in the sibling repo. Details and the
evidence bar → `renogy-curation-and-flags`. No curation change without a
capture or live observation.

### 2. Writability = literal 1 in ops — never a bitmask OR
`ops` on the wire is a LIST drawn from `{1,2,4,5,7}`. `5` and `7` are
composite codes meaning "read + subscribe" — despite `7 == 4+2+1` in binary,
**neither implies write**. Write exists only when the literal code `1` is
separately present. `discovery._parse_ops` implements this; PROTOCOL.md §7.4
documents it. This is the twice-bitten rule: OR-ing raw integers surfaced
every `[2,4,5,7]`-shaped pure reading (TPMS pressure, shunt SOC, tank ratio,
daily energy counters) as a writable Number/Select — fixed in 0.2.4 and again
properly in 0.2.7 (commits `831cd77`, `b1d260e`). Do not "simplify" it back.

### 3. int64 DIDs travel as strings
`did` is int64; JSON float64 mangles it (`...5944 → ...6000`). Use `did_str`
everywhere — config entry, device registry identifiers, sp construction,
dict keys. `auth.refresh_rtm_token` reads the response as text,
`json.loads()`es it, and prefers `didStr` over the numeric `did` (Python's
parser keeps int precision; the regex-before-parse discipline is the TS
reference's, for float64 `JSON.parse`). `RenogyDevice.did` (`api/models.py`)
converts back to int only where the wire genuinely wants an integer (the
`gwm.devs` RPC payload, op-9 connect) — Python ints are arbitrary-precision
so this is lossless, but never round-trip a did through float or JS-style
JSON.

### 4. Every token rotation is persisted immediately
The refresh token dies on every use. `RenogyAuth` takes an
`on_token_refresh` callback; the coordinator wires it to
`hass.config_entries.async_update_entry` (`_persist_tokens`) so every
rotation (access-token refresh AND rtm-token rotation) lands in the config
entry before anything else happens. HTTP **401 and 999 are both**
refresh/auth-failure triggers (`auth._refresh_access`, `rest._get`/`_post`
retry-once). The account password is NOT stored — removed in 0.4.0 (commit
`7a864fa`, config-entry v1→v2 migration in `__init__.async_migrate_entry`);
re-login only ever happens with freshly user-entered credentials via the
reauth flow. Never log request bodies: login sends the password cleartext
over TLS.

### 5. All writes are validated, and all control routes through one door
`coordinator.async_write` checks, in order: the device's
`driving_mode.ctrl_sp_blacklist`, that the sp exists in the discovered
schema, `field.writable`, then `_validate_write_value` (type 1/2/3 and
min/max bounds — a deliberate mirror of the sibling's
`packages/core/src/discovery.ts validateWrite`). Only then does it issue
op-1. HA's UI clamps inputs, but service calls and automations bypass the
UI — this validation is the last line before a physical circuit. Every
platform's control handler (`switch`, `light`, `number`, `select`) calls
`async_write`; `scene.run` goes through `async_run_scene` and is a **batch
write to physical circuits** — treat it with identical care. Ack `code 0` =
success, `code 14` = queued (state confirmation arrives as an op-7 push, do
not read back).

## Resilience design (why each piece exists)

- **RPC retry with backoff** — `discovery._rpc_with_retry` (3 attempts, 0.3 s linear backoff) wraps `rtm.rpc`, which itself retries timeouts 3×. Rationale: the connect-time discovery burst is concurrent (semaphore 4) and a dropped frame can surface as an outright `RenogyRTMError`, not just a timeout. Mirrors the sibling's `withRetry`.
- **Non-destructive device merge** — `coordinator._merge_devices`: if a rediscovery (typically on reconnect) resolves a known device to zero fields with the same pid, keep the prior schema (updating only `online`/`name`) instead of tearing down all its entities over a transient RPC drop. A device genuinely absent from the fresh list is still removed. Mirrors the sibling's `_runLive` prior-snapshot merge.
- **Phantom-instance dropping** — `_drop_phantom_instances`: the schema advertises every tank/temp/TPMS slot the model supports (`ai_N`, `temp_N`, `tp_state_N`), wired or not. A slot is kept only if some **non-writable** field of it seeded a live value — because writable settings fields (calibration, thresholds) answer with firmware defaults even on unbound slots and would make every phantom look live. Runs after seed reads, before subscribe.
- **Reconnect loop** — `schedule_reconnect` → `_reconnect_loop`: exponential backoff 2 s → 30 s (`RTM_RECONNECT_DELAY_MIN/MAX` in `const.py`), fires availability False on entry and True on success, exits on shutdown.
- **Unexpected-disconnect wiring** — the 0.4.0 lesson (commit `1da7fd8`): the RTM reader exiting unexpectedly previously notified nobody, so entities stayed "available" showing stale data forever. `RenogyRTM._reader`'s `finally` block now fires an unexpected-disconnect callback (suppressed during intentional `disconnect()` via `_closing`), which the coordinator wires to `schedule_reconnect`. If you refactor `rtm.py`, preserve this path — it is the only thing that notices a dead socket.
- **Scenes are best-effort** — a REST failure in `_refresh_scenes` logs and returns; scene polish must never block telemetry startup.

## Port-parity contract with the sibling repo

`renogy-gateway` (the TS monorepo, read-only sibling) is **canonical**:
protocol/curation fixes land there first or must be mirrored there. Keeping
these pairs in step is the hardest ongoing problem → see
`renogy-curation-parity-campaign`. Verified mirror pairs (2026-07-12):

| ha-renogy-gateway | renogy-gateway (canonical) | What must match |
|---|---|---|
| `coordinator._validate_write_value` | `packages/core/src/discovery.ts` `validateWrite` | type/bounds semantics |
| `api/discovery._parse_ops` | `discovery.ts` `opsToCaps` (`OP_WRITE = 1`) | literal-1 write rule |
| `api/discovery._rpc_with_retry` | `discovery.ts` `withRetry` | retry shape |
| `coordinator._merge_devices` | `discovery.ts` `_runLive` prior merge | non-destructive semantics |
| `const.py _DIAGNOSTIC_PATTERNS` | `apps/hass-bridge/src/filter.ts` `diagnosticPatterns` | pattern list, verbatim |
| `api/discovery` force-readonly sets (incl. `_FORCE_READONLY_LEAVES_BY_PID`) | `packages/core/src/params.ts` (`PARAM_FORCE_READONLY_BY_PID` etc.) | leaf/pid sets |
| `api/discovery._SKIP_NAMESPACES` | `params.ts PARAM_HIDE_NS` + `apps/dashboard/src/worker/bridge.ts SKIP_SUBSCRIBE_NS` | namespace set (intent, not verbatim — HA hides fewer) |
| `api/labels.py` (`LABELS`, `CURATED_OPTIONS`, `ZH_OPTION`) | `params.ts` same names | curation content |
| `api/discovery._get_firmware` | `bridge.ts formatFirmware` | 2-3-3 digit packing |

When you change either side of a pair, change (or file work for) the other,
and say so in the commit message. Cross-repo docstrings already name their
mirrors — keep that convention.

## Entity platform mapping (from the platform files' filters)

All platforms iterate `coordinator.devices[*].fields` at setup; the field's
shape decides the platform. In evaluation order of intent:

| FieldSpec shape | Platform / class |
|---|---|
| writable bool `.state` with writable `.ratio` sibling | `light.RenogyLight` (brightness = ratio 0-100 → 0-255) |
| writable bool, no ratio sibling, has readable power/current/voltage/ratio sibling on same channel | `switch.RenogySwitch` (load switch) |
| writable bool, no ratio, no measurement sibling | `switch.RenogySwitch` with `EntityCategory.CONFIG` (standalone toggle) |
| writable int/float, no options, not a light's `.ratio` | `number.RenogyNumber` (CONFIG, box mode; missing bounds → ±1,000,000 fallback) |
| writable with `options` | `select.RenogySelect` (CONFIG; labels via `ZH_OPTION`) |
| read-only int/float, no options | `sensor.RenogySensor` (unit/device-class/scaling via `_UNIT_MAP`, incl. mA/mV/mW down-scaling) |
| read-only with `options` | `sensor.RenogyEnumSensor` (without this, read-only enums matched nothing and vanished) |
| read-only bool | `binary_sensor.RenogyBinarySensor` |
| device `protocol` metadata | `sensor.RenogyConnectionTypeSensor` (static, diagnostic; guarantees metadata-only devices get an entity) |
| Manual scene | `button.RenogySceneButton` (runs `scene.run`) |
| Auto scene | `switch.RenogyAutoSceneSwitch` (arm/disarm via REST `updateScene`; deliberately NOT CONFIG) |

Read-only fields matching `const.is_diagnostic_field` get
`EntityCategory.DIAGNOSTIC`. Only field types 1/2/3 (bool/int/float) survive
discovery (`_ENTITY_TYPES`); type 8 (func) and 7/ref (objects) are expanded
or skipped there, not in platforms. If you add a platform, its filter must be
disjoint from the above or a field will spawn duplicate entities.

## Known weak points (stated plainly, as of 2026-07-12)

- **`scene.run` has never been exercised live.** PROTOCOL.md §8.3 is headed "model confirmed; run untested live", yet `coordinator.async_run_scene` and the button platform ship it. The frame shape is inferred from the schema (`type:8` func, `{sceneId}`), not a capture. First live run requires explicit owner permission and should be logged as the confirming evidence.
- **Reconnect does a full rediscovery.** `_reconnect_loop` calls `_connect_and_discover`, repeating the whole gwm.devs/get_product/get_model burst plus all seed reads and subscribes on every reconnect. Correct but expensive on a flappy connection; the model cache lives only per-`RenogyDiscovery` instance (which survives reconnects, softening this).
- **No options flow.** Verified: no `OptionsFlow` anywhere. Nothing is user-tuneable post-setup (no polling knobs to tune, but also no way to hide noisy entities without the entity registry).
- **Curation drift vs the sibling.** The mirror pairs above are maintained by hand and discipline; there is no automated parity check. `_SKIP_NAMESPACES` already intentionally diverges (HA hides fewer namespaces than the dashboard) — divergence-by-intent and divergence-by-neglect look identical without the campaign skill's ledger.
- **Device grouping is flat by did_str.** `entity.py` notes it: a multi-namespace device (the inverter's ac_input + ac_output + charger) cannot split into separate HA devices. Checked against the 2026-07-05 inverter HAR and accepted; revisit only with a design, not a patch.
- **Entity sets are fixed at setup.** Platforms build entities once from the discovery snapshot; a device added mid-session appears only after `_merge_devices` on reconnect AND a config-entry reload — there is no dynamic entity addition path.
- **`config_flow` reauth only refreshes tokens** — it does not re-run gateway selection, so a gateway renamed/replaced on the account keeps its old entry data.

## Provenance and maintenance

Facts above verified 2026-07-12 against v0.5.1 (`dc3c11f`). Re-verify with:

- Layer purity: `grep -rn "homeassistant" custom_components/renogy_gateway/api/` (expect no hits) and `grep -rn "from \.\." custom_components/renogy_gateway/api/` (expect only the `HIDE_LEAVES` exception).
- Push model: `grep -n "should_poll\|DataUpdateCoordinator" custom_components/renogy_gateway/entity.py custom_components/renogy_gateway/coordinator.py` (expect `_attr_should_poll = False`, no DataUpdateCoordinator).
- ops rule: `grep -n "literal" custom_components/renogy_gateway/api/discovery.py docs/PROTOCOL.md | grep -i ops` and read `_parse_ops`.
- Token persistence: `grep -n "_persist_tokens\|on_token_refresh\|999" custom_components/renogy_gateway/coordinator.py custom_components/renogy_gateway/api/auth.py custom_components/renogy_gateway/api/rest.py`.
- Write validation: `grep -n "async_write\|_validate_write_value\|ctrl_sp_blacklist" custom_components/renogy_gateway/coordinator.py` and confirm every platform's control handler calls `coordinator.async_write`.
- Mirror pairs: diff the named symbols, e.g. `grep -n "validateWrite\|opsToCaps\|withRetry" ../renogy-gateway/packages/core/src/discovery.ts` and `grep -n "diagnosticPatterns" ../renogy-gateway/apps/hass-bridge/src/filter.ts` against their HA counterparts.
- scene.run status: `grep -n "untested" docs/PROTOCOL.md` (if the §8.3 header no longer says "run untested live", update the weak-points section).
- Options flow: `grep -rn "OptionsFlow" custom_components/` (a hit means the weak point is fixed — update it).
- Version/commits: `git log --oneline -5` and `git show --stat 7a864fa 1da7fd8`.
