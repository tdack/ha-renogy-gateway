---
name: renogy-protocol-reference
description: >
  Working reference for Renogy's private DC Home gateway API as used by this
  integration. Load when reasoning about auth or tokens (access/refresh/rtmToken,
  401/999, app-register, refresh-token, SYS001/SYS003/DMC400), RTM WebSocket
  frames (op codes 1/2/3/4/6/7/8/9, sp topics, connect-ack, ping/pong), schema
  discovery (gwm.devs, get_product, get_model, ops semantics, inherit/ref),
  writes and control encoding (op-1, code 14, ctrl_sp_blacklist), scenes
  (getUserScenes, scene.run), int64 DID precision, userdata_str.config labels,
  or any other wire-level question about what the protocol does or means.
---

# Renogy DC Home protocol — working reference

Date-stamped 2026-07-12. Condensed from `docs/PROTOCOL.md` (the protocol
document of record, 485 lines — read it in full for depth) and the actual
implementation under `custom_components/renogy_gateway/api/`. Everything here
traces to one of those two sources; confidence labels ([confirmed] /
[inferred] / [untested]) are PROTOCOL.md's own — never upgrade one.

**When NOT to use this skill:**
- Live symptom triage (integration broken right now, what to check first) →
  `renogy-debugging-playbook`.
- How a protocol fact was established, capture archaeology, evidence standards
  → `renogy-failure-archaeology` / `renogy-analysis-and-evidence`.

**Sibling repo:** `renogy-gateway` (read-only, canonical TypeScript project)
holds `reference/renogy_client.py` (validated Python reference), `captures/`
(HARs — the evidence bar; they contain credentials, never quote tokens), and
its own `docs/PROTOCOL.md`, which is a **superset** of this repo's copy (see
"Two PROTOCOL.md copies" below).

**THE SAFETY RULE:** op-1 writes and `scene.run` switch real physical
circuits. NEVER live-test either without explicit human permission.

---

## 1. Glossary (read first)

| Term | Meaning |
|---|---|
| Gateway / ONE Core | The Renogy hub device. All child devices sit behind it; scenes and `gwm.*` RPCs are scoped to its `did`. |
| Rig | One gateway plus its child devices — the whole installed system. |
| `did` | Device ID, an int64. As a raw JSON number it **loses precision** through float64 parsing — never trust a parsed `did`. |
| `did_str` | The same ID as a string, precision-safe. Always prefer it (PROTOCOL.md §3). |
| `pid` | Product ID (e.g. `000F003C` inverter, `smartDistributionBox`). Keys `gwm.get_product`. |
| `sku` | Marketing model code (e.g. `RSHCB-C02P-G2`). Display only — never derive behaviour from it. |
| `sp` | "Topic path": `"<id>/<namespace>.<field>"`, the address of one field on one device. Also the name of one schema entry in `get_model`'s `sps` list. |
| Namespace | A capability model a device exposes (e.g. `distribution_box`, `tpms`, `charger`). A device's role IS its namespace set. |
| Leaf | The final segment of a field path (e.g. `state` in `dc_10a_1.state`). |
| `channel_key` | The instance segment of a field path (e.g. `dc_10a_1` from `distribution_box.dc_10a_1.state`); the key user labels attach to. |
| RTM | "Real-time messaging" — the custom MQTT-style pub/sub/RPC protocol over `wss://gateway.renogy.com/rtm/ws`. Frames are JSON. |
| Op code | The `op` field of an RTM frame: what kind of frame it is (see §4). |
| Access / refresh token | Account-level pair from `do_login`. Access = 15-min HS512 JWT sent as `x-token`; refresh **rotates** on every use. |
| rtmToken | A separate device-level JWT that authenticates the RTM WebSocket upgrade (header `device-token`). ~7-day life, rotates via `refresh-token`. |
| Schema / model | The self-published field description a namespace returns from `gwm.get_model` (type, unit, min/max, `ops`, …). |
| Curation | This project's defensive layer of overrides where the schema lies (force-readonly lists, hidden namespaces, curated enum options). |

## 2. Hosts (PROTOCOL.md §1) — [confirmed]

| Host | Purpose | Used here? |
|---|---|---|
| `https://gateway.renogy.com` (`/api/v1`, `/api/v2`) | Auth, device lists, scenes | Yes — REST |
| `wss://gateway.renogy.com/rtm/ws` | Telemetry **and control** | Yes — the core |
| `wss://gateway.renogy.com/api/v1/ws/msg` | Notification counts | No |
| `dataaccess.renogy.cn` | App analytics | No — ignore |

This is the private backend the phone app uses, richer than the official
developer API at `platform.renogy.com`.

## 3. Auth (PROTOCOL.md §2, §2.1) — [confirmed]

Implementation: `custom_components/renogy_gateway/api/auth.py` (`RenogyAuth`).

### 3.1 Account tokens

- **Login** `POST /api/v1/account/app/do_login`, body
  `{"loginType":0,"identifier":<email>,"credential":<password>}` →
  `{accessToken, refreshToken}`. Password travels **cleartext over TLS** —
  never log request bodies. → `RenogyAuth.login()`.
- **Access token**: HS512 JWT, **15-minute** life, sent as header `x-token`.
  Claims include `device_uuid` and `exp`. `auth.py` decodes claims unverified
  (`_jwt_claims`) and refreshes proactively 60 s before expiry
  (`REFRESH_SKEW`, `_access_token_fresh` → `ensure_fresh`).
- **Refresh** `POST /api/v1/account/app/do_refresh` body
  `{"refreshToken": ...}` → a NEW pair. **Refresh tokens ROTATE — the old one
  dies. Persist the new pair every time or you lock yourself out.**
  `_refresh_access()` persists immediately via the `on_token_refresh`
  callback (the coordinator writes it into the HA config entry).
- **Expiry signal**: the API returns HTTP **999 as well as 401** for a stale
  access token. Treat both as "refresh and retry" — `rest.py`'s `_get`/`_post`
  retry once on `(401, 999)`; `auth.py` treats them on `do_refresh` itself as
  "re-login required" (`RenogyAuthError`).

### 3.2 Static client headers

Every call sends `auth.py`'s `CLIENT_HEADERS` (checked loosely by the server):
`app-version: 1.8.82`, `device-version: 26.5`, `device-mode: iPad8,6`,
`device-manufacturer: Apple`, `request-channel: ios`, the matching
`User-Agent`, plus `identity-uuid` (a persistent local UUID, seeded from the
access token's `device_uuid` claim after login).

### 3.3 SERVERID cookie vs device-token

PROTOCOL.md §2 says keep the `SERVERID` sticky-session cookie jar across
calls, but §4 records the **[confirmed]** fact that RTM auth uses the
**`device-token` HTTP header carrying the rtmToken JWT — NOT the cookie**.
This repo relies on aiohttp's session cookie jar and sends `device-token`
explicitly (`rtm.py` `_open_ws`).

### 3.4 rtmToken lifecycle

Two paths, both in `auth.py`:

| Situation | Endpoint | Body | Implementation |
|---|---|---|---|
| Cold boot (no stored token) | `POST /api/v2/device/app-register` | `{"pid":"003F0000","sn":"<device_uuid>#<email>","nodeType":4}` (constants `_APP_REGISTER_PID`, `_APP_NODE_TYPE`) | `RenogyAuth._app_register()`, called from `login()` |
| Rotation (have any prior token, even expired) | `POST /api/v2/device/refresh-token` | `{"token": <prev rtm token>}` | `RenogyAuth.refresh_rtm_token()` |

- `app-register` returns `{did, didStr, token}`: the first rtmToken plus the
  RTM-connect DID. Needs only the account `x-token` + `identity-uuid` — so
  onboarding needs **only email + password**. **[SOLVED 06-12, CONFIRMED
  LIVE 06-14]** (PROTOCOL.md §2.1).
- `refresh-token` is rotation-only. Its error responses distinguish misuse:
  `{}`/`null` → `SYS003 "token can not null"`; `{"token":""}` → 500 `SYS001`;
  an account access/refresh token → `DMC400 "User data anomaly detected"`.
- The minted rtmToken lives **~7 days**, but the endpoint accepts a token
  **weeks past expiry** — keep rotating and it self-renews indefinitely.
  **[confirmed 06-12]**
- rtmToken JWT claims: `{expireTs, sn}` where `sn = "<device_uuid>#<email>"`.
  The `sn` claim is NOT the DID.

## 4. RTM protocol (PROTOCOL.md §4) — [confirmed]

Implementation: `custom_components/renogy_gateway/api/rtm.py` (`RenogyRTM`).

### 4.1 Handshake

1. Rotate the rtmToken (`connect()` calls `refresh_rtm_token()` every
   connect).
2. Open the WS upgrade with header `device-token: <rtmToken>` (plus
   `Origin: https://gateway.renogy.com`). On **403** (stale RTM session):
   rotate the token and **retry once** (`_open_ws`).
3. Send op-9 connect:
   `{"op":9,"data":{"did":<rtm-did>,"expiryInterval":-1,"cleanStart":true,"nodeType":4}}`.
   The `did` here is the **RTM-connect DID** from `refresh-token` /
   `app-register` — NOT a device did. Don't mix them.
4. Receive op-8 connect-ack: `code=0` + `data.token` (session JWT) = success;
   `code=3` + no data = **wrong DID** (classic float64 precision loss).
5. The server sends literal `ping` **text frames**; reply with the text
   `pong` (`_reader()` handles this; aiohttp's own `heartbeat=30` covers
   WS-level ping too).

### 4.2 Frame fields

`op` (operation) · `opid` (client message id) · `wopid` (echoed opid on
responses — the correlation key `_call()`/`_dispatch()` match on) · `sp`
(topic path) · `data` (payload) · `ack` · `qos` · `code` (0 = ok) · `sop`.
Note: RPC responses can arrive as op-7 frames carrying a `wopid` — `rtm.py`
resolves pending correlation before treating op-7 as telemetry.

### 4.3 Op codes

| op | direction | meaning | `RenogyRTM` method |
|---|---|---|---|
| 9 / 8 | send / recv | connect / connect-ack (+ session token) | `connect()` |
| 2 → 3 | send → recv | read a value (response carries `wopid`) | `read(sp)` |
| 4 | send | subscribe; telemetry then streams as op 7 | `subscribe(sp)` |
| 7 | recv | telemetry push `{sp, data}` | `_dispatch` → callbacks |
| 6 | send | RPC method call (`gwm.get_product`, `scene.run`, …) | `rpc(sp, data)` |
| **1** | send | **WRITE / SET — the control path** | `write(sp, value)` |

### 4.4 Topic format

`"<id>/<namespace>.<field>"`, e.g.
`4623589794012005944/distribution_box.dc_10a_3.state`. `<id>` is a device
`did`, or the shorthand **`1`** for gateway-local RPCs (`1/gwm.devs`,
`1/gwm.get_model`, …).

## 5. The int64 hazard — [confirmed]

DIDs, scene ids, `gatewayDeviceId`, `userId`, `deviceId` are int64. Parsing
them as JSON numbers through float64 silently corrupts the last digit(s)
(`4623589794012005944 → 4623589794012006000`). Consequences: op-9 connect-ack
`code=3`, `gwm.devs` `code=6`, writes to the wrong device.

This repo's rule (Python `json` preserves big ints natively, so it is milder
than the TypeScript reference's regex extraction, but the discipline stands):

- Always prefer `did_str` and carry DIDs as **strings**
  (`auth.py refresh_rtm_token()` prefers `didStr` over `did`;
  `rest.py get_gateways()` prefers `did_str`; `discovery.py _get_devices()` /
  `_resolve_device()` prefer `did_str`; `rest.py get_scenes()` stringifies
  scene `id`s).
- Convert to `int` only at the wire boundary where the protocol requires a
  bare JSON number (`rtm.py connect()` op-9 `did`; `discovery.py` `gwm.devs`
  `dids`/`gatewayId`; `coordinator.py async_run_scene()` `sceneId`).

## 6. Control encoding & write safety (PROTOCOL.md §4) — [confirmed by live write tests]

- **On/off**: op-1 write to `<box>/distribution_box.<ch>.state` with a JSON
  **boolean**.
- **Dim / duty cycle**: op-1 write to `...<ch>.ratio` with an **int percent**
  (e.g. `33`). Raising `ratio` turns the channel on; switch off with
  `.state=false`.
- **ACK** (matching `wopid`): `code=0` = explicit success, `data` echoes the
  value. `code=14` = **accepted/queued** — the real new state arrives shortly
  as an op-7 push. **Never issue an op-2 read-back immediately after a
  write** — the server returns stale cached data. Subscribe and wait for the
  push. `coordinator.py async_write()` accepts `(0, 14)` and warns on
  anything else.

**Write validation chain** (`coordinator.py async_write()` +
`_validate_write_value()`; mirrors the sibling's `validateWrite`):

1. sp must resolve to a discovered field, else error.
2. Field's derived `ops` must include write (`field.writable`).
3. The relative path must NOT appear in the device's
   `driving_mode.ctrl_sp_blacklist` (read at discovery,
   `discovery.py _get_ctrl_sp_blacklist()`).
4. Value must match the schema `type` (bool/int/float — bools are rejected
   where ints are expected) and sit within `min`/`max`.

And, again: **seek explicit human permission before executing any live op-1
write or `scene.run`, including when testing or debugging.**

## 7. Self-describing discovery (PROTOCOL.md §7) — [confirmed]

Implementation: `custom_components/renogy_gateway/api/discovery.py`
(`RenogyDiscovery`). Three op-6 RPCs on `1/...` let a client configure itself
for ANY rig with zero hardcoding. Device types, channel lists, units, and
controllability come from here — never from SKU prefixes or literal tables.

### 7.1 `gwm.devs` — device inventory [confirmed two-step]

Two **sequential** RPCs on `1/gwm.devs` (`_get_devices()`):

1. `{dids:[<gatewayDid>]}` — registers the gateway into the RTM session
   (response has `"session":true` and also carries the gateway's own device
   entry). **Skipping step 1 causes `code=6` on step 2.**
2. `{gatewayId:<gatewayDid>}` — returns child devices, each with `did_str`,
   `pid`, `sku`, `online`, `text` (name), `nodeType`, `typeId`.

`online` is volatile — always read it live, never cache it as a device
property.

### 7.2 `gwm.get_product` — capability namespaces

`{name: <pid>}` → `{models: string[], pid, nodeType, typeId, text, protocol,
model_ext}`. `models` is the namespace list. **A device's role IS its
namespace set** — worked examples:

| pid | namespaces |
|---|---|
| `smartDistributionBox` | `thing, distribution_box, customAlarm, userdata_str, driving_mode` |
| inverter `000F003C` | `thing, pv_input, charger, charge_params, ac_input, ac_output, ac_load_driver, battery_input, inverter_state, …` (sibling PROTOCOL.md completes the list: `charger_history, inverter_history, battery_volt_sensor, battery_temp_sensor, signal`) |
| MPPT `000E002E` | `thing, pv_input, charger, charger_params, charger_history, …` |
| TPMS `00340003` | `thing, tpms` |

→ `_get_product()`. `discovery.py` then skips protocol-internal namespaces
(`_SKIP_NAMESPACES`: `thing`, `gwm`, `userdata_str`, `driving_mode` — both
special-cased separately — `scene` — dedicated platform — etc.).

### 7.3 `gwm.get_model` — the field schema

`{name: <namespace>}` → `{name, mid, alarms[], inherit?, sps[]}`. Each `sps`
entry describes one field:

| key | meaning |
|---|---|
| `name` | stable, language-neutral field key — **use this**, not `text` |
| `type` | `1` bool · `2` int · `3` float · `4` string · `5` array · `7` obj · `8` func (RPC method) · `9` series (time-series) |
| `unit` | display unit (`%`, `W`, `V`, `A`, `°C`, `kPa`) when present |
| `coef`, `precision` | scaling metadata + decimal places (see §8 — do NOT apply `coef` to RTM values) |
| `min`, `max` | value bounds — used for write validation |
| `options` | enum `[{key, value}]` (e.g. tpms `state`, `socRule`) |
| `ops` | allowed operations — a small **enum**, not a bitmask; see §7.4 |
| `ref` | field is an object of another model — resolve by name (tpms `tp_state_N` → model `tpms_state`) |
| `inherit` | merge a parent model's `sps` (`dc_output_adjustable` inherits `dc_output_ext`) |
| `text`, `desc` | human label — **often Chinese**; treat as optional |

→ `_get_model()`/`_fetch_model()` (resolves `inherit` recursively, child
overrides parent by name) and `_expand_sp()` (resolves `ref` with a cycle
guard, recurses inline type-7 objects, drops type-8 funcs).

### 7.4 `ops` semantics — READ THIS TWICE (it bit this project twice)

Real `ops` values arrive as a **list** drawn from `{1, 2, 4, 5, 7}`:

| code | meaning |
|---|---|
| `1` | **write** — contributed ONLY by this literal appearing in the list |
| `2` | read |
| `4` | subscribe |
| `5`, `7` | **recognized composite codes meaning "read + subscribe"** — NOT the sum of binary digits |

**NEVER OR the raw integers together.** Although `5 == 4+1` and `7 == 4+2+1`
in binary, neither implies write. Worked example [confirmed against real
captures]: `inverter_history.Bat_Chg_Energy` reports `ops:[2,4,5,7]` (no
literal `1`) and is genuinely read-only; `dc_output_ext.state` reports
`ops:[1,2,4,5,7]` (literal `1` present alongside `5`/`7`) and is genuinely
writable. A client that folds `7` into a bitmask sets the write bit from a
pure sensor reading — this misread every `[2,4,5,7]`-shaped field as writable
and **bit the ha-renogy-gateway port twice** before being traced back to
capture data. The correct decoder is `discovery.py _parse_ops()`: read ⇔
`values ∩ {2,5,7}`, subscribe ⇔ `values ∩ {4,5,7}`, write ⇔ `1 ∈ values`,
full stop.

Everything derived from the schema (PROTOCOL.md §7.4):

- **Controllable** ⇔ `ops` contains the literal `1`.
- **Dimmable** ⇔ the channel has a writable `ratio` sibling (model
  `dc_output_adjustable`); `userdata_str.config`'s `controlMode` (0 switch,
  1 dimmer) is a second, config-driven signal.
- Units, scaling, type, enums, bounds — straight from the field entry.

Worked box examples: `dc_output_ext`: `state` (bool, writable), `power` (int
W, read-only), `current`/`voltage` (float, read-only). `dc_output_adjustable`
= inherit `dc_output_ext` + `ratio` (int %, 0–100, writable). `relay`:
`state` writable. `analog_input_r` (tanks): `ratio` read-only, `mode` with
`options`.

### 7.5 What discovery does NOT give you

- **User-assigned names** ("Bedroom Light"). Read
  `<box>/userdata_str.config` (op-2). The `data` is a JSON-encoded string,
  **sometimes double-encoded — parse up to twice**. The real shape
  (PROTOCOL.md §5, confirmed against a capture) is NOT a flat map:
  **namespace-qualified keys** with **object values**:
  `{"distribution_box.dc_10a_1": {"name": "Bedroom Light", "channelEnable":
  true, "controlMode": 0, ...}, ...}`. Strip the namespace prefix before
  matching against `channel_key`; the display name is `value.name`; an
  unconfigured channel reads back the placeholder **`"--"`** — treat that as
  unset, fall back to the schema-derived name. →
  `discovery.py _get_user_labels()` + `_apply_labels()`.
- **The control blacklist**: `driving_mode.ctrl_sp_blacklist` is a list of
  relative sp paths the device refuses writes for. A write validator must
  honour it. → `_get_ctrl_sp_blacklist()`, enforced in
  `coordinator.py async_write()`.

### 7.6 Practicalities: cost & caching

Covering every namespace takes **~25–30 `get_model` calls**, but the schema
is **static per `pid` + firmware version**. PROTOCOL.md §7.6 recommends
persistent caching (shared `product:<pid>` / `model:<ns>` entries + a
per-rig snapshot for instant first paint, then live revalidation/`diffRigs`)
— that guidance describes the **sibling TypeScript project**. What THIS repo
actually does (verified in `discovery.py` / `coordinator.py`): a fresh
`RenogyDiscovery` per config entry with an **in-memory** `_model_cache`
(namespace → sps, plus in-flight deduplication so concurrent devices sharing
a namespace await one RPC). Discovery **re-runs on every connect and
reconnect** (`coordinator.py _connect_and_discover()`), with a
non-destructive `_merge_devices()` so a transient zero-field rediscovery
keeps the prior schema; there is **no cross-restart cache**. RPCs run at most
4 concurrently (`_MAX_CONCURRENT`) with 3-attempt backoff retry
(`_rpc_with_retry`) on top of `rtm.py rpc()`'s own 3 retries.

## 8. Known schema inconsistencies (PROTOCOL.md §7.7) — [confirmed via captures]

The schema lies. Defensive checklist — each item is a real, confirmed
deviation with its counter-measure in this repo:

| Inconsistency | Evidence | Defence in this repo |
|---|---|---|
| Read-only fields carry the literal write code `1` | every lowercase `_today` daily counter in `inverter_history` reports `ops:[1,2,4,5,7]` (their PascalCase `_Total` siblings correctly report `[2,4,5,7]`) | `discovery.py _FORCE_READONLY_SUFFIXES = ("_today",)` |
| TPMS readings falsely writable on some rigs | `tp_state_N.{pressure, online, ...}` observed live with the write bit (not in this account's captures) | `_FORCE_READONLY_LEAVES_BY_NAMESPACE["tpms"]` |
| Case-inconsistent leaf names for the same quantity on one device | inverter reports both `voltage` and `battery_input.Voltage` | `_is_force_readonly()` matches case-insensitively; `voltage` in `_FORCE_READONLY_LEAVES` (the one case the app itself special-cases) |
| Some namespaces are never discovered live | no capture ever shows `get_model` for the inverter's `ac_input`/`ac_output`/`battery_input`; the app reads known paths directly | sibling's `registry.ts` hardcodes a fallback; here the AC leaves sit in `_FORCE_READONLY_LEAVES` |
| Identically-named fields disagree across namespaces | `charger.desired_voltage` writable (`[1,2,4,5,7]`), `start_battery.desired_voltage` not (`[2,4,5,7]`) | trust each namespace's own `ops` — never generalise by leaf name |
| Units occasionally in Chinese | `charger.max_current` unit `安培` ("Ampere") on at least one rig | translate known Chinese unit strings; never assume ASCII |

The **sibling repo's PROTOCOL.md** adds three more confirmed items this
repo's copy does not yet carry (verify there before relying on them here):

| Inconsistency | Evidence (sibling §7.7) | Defence in this repo |
|---|---|---|
| `coef` is metadata only — never multiply RTM values by it | `charger.charging_voltage` (`coef=0.1`) reports 13.9 for a real 12 V bus; tpms pressure (`coef=0.01`) reports 398.78 kPa — the gateway pre-scales both reads and writes | `discovery.py` stores `precision` but never applies `coef` |
| `mV`/`mA`/`mW` units genuinely carry milli-unit values | `ac_output.Output_Current` reports 1100 = 1.1 A | a real unit-prefix scale to normalise (×0.001, rebase unit), unlike `coef` |
| Same field means different things per **product type** | `charger.battery_type` is a genuine setting on MPPT/DC-DC chargers, but on the inverter (`000F003C`) it is fixed by the product (its own Chinese `desc` says so) yet still reports the write bit, with live value 14 outside the curated 0–5 range | `_FORCE_READONLY_LEAVES_BY_PID["000F003C"] = {"battery_type"}` |

## 9. Scenes (PROTOCOL.md §8) — [confirmed REST; execution path partly inferred]

Scenes ("Away", "Home", …) are **cloud-stored automations** managed over
REST, scoped to the **gateway** `did`. The RTM `scene` model is the
execution/feedback side. `scene.run` is a batch of physical writes — the
safety rule applies in full.

### 9.1 REST CRUD — `/api/v2/device/scene/*` [confirmed]

Standard authenticated REST (account `x-token`; envelope
`{code:"000000", msg, timestamp, data}`).
Implementation: `custom_components/renogy_gateway/api/rest.py`.

| Endpoint | Meaning | Implementation |
|---|---|---|
| `GET /getUserScenes?gatewayDeviceId=<gwDid>&type=<1|2|3>` | list scenes; type `1` = favourites (starred subset), `2` = manual (run on demand), `3` = auto (condition-triggered, has enable toggle) | `RenogyREST.get_scenes()` fetches type 2 + 3 (mirroring the dashboard) |
| `POST /updateScene` | create / edit / **toggle**: the body is the FULL scene object echoed back, with write-side `isManual` (mirrors `conditionType`: 1 manual, 4 auto); toggling auto = flip `isOpen` | `RenogyREST.update_scene()` → `coordinator.async_set_scene_open()` |
| `GET /getBrokenScenes?...` | scenes referencing a now-missing device; optional health check | not implemented here |

Scene object essentials (§8.2): `id` (**int64 — precision hazard**; `rest.py`
stringifies it immediately), `sceneName`, `isOpen`, `conditionType`,
`conditions[]`, and `operations[]` where `operationParameter` is a **string**
— either JSON-encoded (e.g. `dc_loads_ctrl` `{"loads": <12-bit channel
bitmask>, "state": bool}`) or a bare scalar (`"false"`).

### 9.2 RTM scene model (§8.3) — [model confirmed; run untested live]

`gwm.get_model {name:"scene"}` on the gateway exposes (all funcs type 8,
called op-6 on `<gwDid>/scene.<fn>`): `run {sceneId}` (execute), `query`,
`save`/`del`, `restore_scene`, plus subscribables `scene_trigger` (last-fired
scene id), `scene_trigger_ts`, `update_time_local` (bumps when scenes change
— re-fetch on push), `log`/`log_ts`.

**Execution gap — preserve this label:** PROTOCOL.md §8.3 marks scene
execution "**run untested live**": no capture shows a Run; the intended path
is op-6 `<gwDid>/scene.run {sceneId}` — **verify live before relying on it**
(fallback: replay each `operation` as op-1 writes). What this repo
implements anyway: `rtm.py run_scene()` issues exactly that RPC, and
`coordinator.py async_run_scene()` exposes it (accepting ack codes 0/14) for
scenes already fetched via REST. Auto-scene arming goes through REST
`updateScene`.

## 10. Two PROTOCOL.md copies — divergence map (checked 2026-07-12)

This repo's `docs/PROTOCOL.md` is a carried-over copy (its own header note
says its `packages/core/...` path references are provenance, not paths that
exist here). The sibling `renogy-gateway/docs/PROTOCOL.md` is a **strict
superset** apart from that note. Sibling-only content: the inverter
online-status caveat (its ✗/✓ in §3 is a snapshot — always read `online`
from `gwm.devs`); the inverter's complete namespace list (§7.2) and extra §6
namespaces (`ac_load_driver`, `inverter_state`, `battery_volt_sensor`); and
the three extra §7.7 items tabulated in §8 above (`coef` metadata-only,
milli-unit fields, per-pid `battery_type`). When the copies disagree, treat
the sibling as ahead and this repo's implementation comments
(`discovery.py`) as the local record.

## Provenance and maintenance

Everything above traces to `docs/PROTOCOL.md` (in-repo copy of record) or to
`custom_components/renogy_gateway/api/{auth,rest,rtm,discovery}.py` and
`custom_components/renogy_gateway/coordinator.py`. Re-verify with:

- Diff the two protocol docs: `diff docs/PROTOCOL.md ../renogy-gateway/docs/PROTOCOL.md`
- Auth endpoints/headers: `grep -n "do_login\|do_refresh\|app-register\|refresh-token\|CLIENT_HEADERS\|999" custom_components/renogy_gateway/api/auth.py custom_components/renogy_gateway/api/rest.py`
- RTM ops & handshake: `grep -n '"op"\|device-token\|pong\|code' custom_components/renogy_gateway/api/rtm.py`
- ops decoding & curation lists: `grep -n "_parse_ops\|_FORCE_READONLY\|_SKIP_NAMESPACES" custom_components/renogy_gateway/api/discovery.py`
- Write validation & scenes: `grep -n "async_write\|ctrl_sp_blacklist\|run_scene\|_validate_write_value" custom_components/renogy_gateway/coordinator.py`

Update this skill whenever `docs/PROTOCOL.md` gains a section or a confidence
label changes ([untested] → [confirmed] especially for `scene.run`).
