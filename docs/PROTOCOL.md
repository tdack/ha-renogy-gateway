# Renogy DC Home — Private Gateway API & RTM Protocol

> **Note on this copy:** this document was carried over from the (private)
> TypeScript reference project this integration was originally ported from,
> for protocol documentation purposes. File-path references below
> (`packages/core/src/...`, `apps/dashboard/...`, `apps/hass-bridge/...`,
> `captures/*.har`) point at that project's structure, not at anything in
> this repo — they're kept as provenance for *why* a given protocol detail
> is known, not as paths you can follow here. The actual implementation in
> this repo lives under `custom_components/renogy_gateway/`.

Reverse-engineered from captured iOS-app traffic (Proxyman). This is the source
of truth for the client. `reference/renogy_client.py` is a validated Python
implementation of everything below; port from it.

> Status legend: **[confirmed]** seen in traffic · **[inferred]** strongly
> implied but not directly stated · **[untested]** not yet exercised live.

---

## 1. Hosts / channels

| Host | Purpose | Use it? |
|---|---|---|
| `gateway.renogy.com` (`/api/v1`, `/api/v2`) | Account, auth, config, device list | **Yes** — REST |
| `wss://gateway.renogy.com/rtm/ws` | Real-time device telemetry **and control** | **Yes** — the core |
| `wss://gateway.renogy.com/api/v1/ws/msg` | Community/notification unread counts only | No |
| `dataaccess.renogy.cn` (`/sa?project=production`) | SensorsAnalytics app-usage tracking (`$AppClick`) | No — ignore |

This is a different, richer backend than the official developer API at
`platform.renogy.com` (which is signed-REST and largely read-only).

## 2. Auth (REST) — [confirmed]

- **Login:** `POST /api/v1/account/app/do_login`
  body `{"loginType":0,"identifier":"<email>","credential":"<password>"}`
  → `data: {accessToken, refreshToken}`.
  ⚠️ Password is sent **cleartext** (no client-side hashing). Keep creds in env.
- **Access token:** HS512 JWT, **15-minute** lifetime, sent as header `x-token`.
  Claims: `id, email, nk, st, support_refresh, device_uuid, jti, iat, exp`.
- **Refresh:** `POST /api/v1/account/app/do_refresh` body `{"refreshToken": "..."}`
  → new `{accessToken, refreshToken}`. **Refresh tokens ROTATE** — the response
  returns a *new* refresh token and the old one dies. **Persist the new one
  every time** or you lock yourself out. Refresh-token JWT has **no `exp`**
  (server-tracked).
- **Auth-expiry signal:** the API returns HTTP **`999`** (not just 401) when the
  access token is stale. Treat 401 **and** 999 as "refresh and retry".
- **Static headers** sent on every call (some are checked loosely):
  `app-version: 1.8.82`, `device-version: 26.5`, `device-mode: iPad8,6`,
  `device-manufacturer: Apple`, `request-channel: ios`,
  `identity-uuid: <= token.device_uuid>`,
  `User-Agent: Renogy/1.8.82 (com.renogy.DCHome; build:2; iOS 26.5.0) Alamofire/5.11.2`.
- **Session cookie:** responses set `SERVERID=...` (sticky backend node). Keep a
  cookie jar across all calls — it matters for the WS upgrade (see §4).

### Useful REST endpoints [confirmed]
- `GET /api/v2/device/getUserGateways` → gateways (the ONE Core), each with `did`.
- `GET /api/v1/device/user/me/homePage/deviceStatus?onlineStatus=0` → home tiles.
- `GET /api/v1/device/user/me/list?gatewayDeviceId=0&isDeleted=0&modeType=1`
  → devices behind a gateway (+ their `did`s).
- `POST /api/v2/device/refresh-token` body `{"token":"<prev rtm token>"}`
  → `{did, token}`. **Rotates** the **RTM device token** (separate from the account
  tokens). JWT claims `{expireTs, sn}`, `sn = "<device_uuid>#<email>"`. **[confirmed
  06-12]** The minted token lives **~7 days** (not ~2082 as previously thought), BUT
  the endpoint accepts an **expired** prior token to rotate — a token 21 days past
  `expireTs` still rotated to a fresh one. So a seed captured **once** keeps working
  indefinitely as long as you keep rotating it.
  - It is purely a *rotation* endpoint: `{}`/`null` → `SYS003 "token can not null"`,
    `{"token":""}` → 500 `SYS001`, account access/refresh token → `DMC400 "User data
    anomaly detected. Please reinstall the app."` (the cold mint uses app-register, §2.1).
- `POST /api/v2/device/app-register` body `{"pid":"003F0000","sn":"<device_uuid>#<email>","nodeType":4}`
  → `{did, didStr, token}`. **Mints the first RTM token** for a never-registered
  device (the cold-boot path; needs only the account `x-token` + `identity-uuid`).
  `pid` is the DC Home iOS app's product id and `nodeType` 4 is the app node — both
  constant. The returned `token` is the rtmToken; `didStr` is the RTM-connect did.

### 2.1 First-token bootstrap — [SOLVED 06-12]

A never-registered device mints its first RTM token via **`app-register`** (above),
*not* `refresh-token`. The genuine cold-boot HAR (new device, no keychain, manual
login) showed: `do_login` → … → `POST app-register` → `/rtm/ws` 101 — no
`refresh-token`/403 dance. So onboarding needs **only email + password**:

1. `do_login` → account tokens (the access token carries `device_uuid` + `email`).
2. `app-register` with `sn = "<device_uuid>#<email>"` → first rtmToken + RTM did.
3. Open `/rtm/ws` with `device-token: <rtmToken>`.

Thereafter rotate with `refresh-token` (which tolerates an expired token). The
earlier "reinstall" capture wasn't a cold boot — the iOS keychain persists the
device_uuid + token across reinstalls, so it still had a prior token to rotate.

`core`'s `RenogyREST.rtmToken()` implements this: app-register when there's no
stored token, refresh-token otherwise. The `scripts/probe-rtm-bootstrap.ts` probe
(which tried refresh-token variants) is superseded by this finding.

**[CONFIRMED LIVE 06-14]** End-to-end cold start verified in production on a fresh
Durable Object (empty token store, no seed). Onboarding a new instance with only
**email + password** minted the first rtmToken via `app-register`, opened
`/rtm/ws`, discovered the rig, and streamed live telemetry — **no seed RTM token
required**. The seed-token field / `npm run seed-tokens` are now purely an optional
override, not part of the happy path.

## 3. Account device IDs (this account — discover dynamically, don't hardcode)

Always use `did_str` from `gwm.devs` responses; the `did` number field loses
int64 precision through `JSON.parse` (e.g. `4623589794012005944 → 4623589794012006000`).

| Device | `did_str` | `sku` | `pid` | online |
|---|---|---|---|---|
| Gateway (ONE Core) | `227162568538456065` | `RSHGWSN-W02W-G3` | `RenogyOneCore` | ✓ |
| Smart Distribution Box | `4623589794012005944` | `RSHCB-C02P-G2` | `smartDistributionBox` | ✓ |
| Shunt 300A | `4838812556313808772` | `RSHST-B02P300-G1` | `SmartShunt300` | ✓ |
| PV Charger (RCC60REGO) | `4774953285866299397` | `RCC60REGO-G2` | `000E002E` | ✓ |
| PV/Battery Charger (RBC50D1S) | `4853068635592169353` | `RBC50D1S-G6` | `0010000C` | ✓ |
| TPMS | `4891324250207717566` | `TPMS` | `00340003` | ✓ |
| Inverter/Charger (RIV1230RCH) | `4766577127497453285` | `RIV1230RCH-24S` | `000F003C` | ✗ |
| Vision (touchscreen UI / OEM frontend) | `4646428229905819205` | — | `002C0000` | ✓ |

RTM-connect `did` (from `refresh-token`, bound to RTM token): `257470607149498369`

The op-9 connect uses the **RTM-connect did** (from `refresh-token`); control and
telemetry topics use the **per-device did** (e.g. the box). These differ — don't
mix them.

## 4. RTM protocol — `wss://gateway.renogy.com/rtm/ws`

A custom **MQTT-style pub/sub/RPC over WebSocket**. Frames are JSON.

### Handshake [confirmed]
1. Ensure a valid RTM token via `POST /api/v2/device/refresh-token`.
2. Open the WS upgrade with HTTP header **`device-token: <rtmToken JWT>`**.
   (Not a cookie — the SERVERID sticky-session cookie is NOT used here.)
3. Observed pattern: open → **403** if RTM session stale → call `refresh-token`
   → reopen with fresh token → **101**. The client should mirror this (retry once on 403).
4. Send connect, receive connect-ack:
   - send `{"op":9,"data":{"did":<rtm-did>,"expiryInterval":-1,"cleanStart":true,"nodeType":4}}`
   - recv `{"op":8,"code":0,"data":{"token":"<session jwt>"}}`
5. Server sends `ping` text frames; reply `pong`.

### Connect-ack codes [confirmed]
- `code=0` + `data.token = <device-session JWT>` — correct DID, full session
- `code=3` + no data — **wrong DID** (float64 precision loss); gwm.devs returns code=6

The op-9 `did` comes from `POST /api/v2/device/refresh-token` response body. The
`did` field is a large int64 JSON number — JavaScript `JSON.parse` loses the last
digit (e.g. `257470607149498369 → 257470607149498368`). Extract it by regex on
the raw response text before parsing. The JWT `sn` claim is NOT the DID — it
carries `UUID#email` for user-scope tokens.

### Frame fields
`op` (operation), `opid` (client msg id), `wopid` (echoed opid on responses),
`sp` (topic path), `data` (payload), `ack`, `qos`, `code` (0 = ok), `sop`.

### Op codes [confirmed]
| op | direction | meaning |
|----|-----------|---------|
| 9 / 8 | send / recv | connect / connect-ack (+ session token) |
| 2 → 3 | send → recv | read a value (response carries `wopid`) |
| 4 | send | subscribe (telemetry then streams as op 7) |
| 7 | recv | telemetry push: `{sp, data}` |
| 6 | send | RPC method call (e.g. `gwm.get_product`, `gwm.get_model`) |
| **1** | send | **WRITE / SET — the control path** |

### Topic format
`"<id>/<namespace>.<field>"` — e.g.
`4623589794012005944/distribution_box.dc_10a_3.state`.
`<id>` may be a device `did`, or `1` as a gateway-local shorthand.

### Control encoding [confirmed by live write tests]
- **On/off:** op 1 write to `<box>/distribution_box.<ch>.state` with a JSON
  **boolean** `true`/`false`.
- **Dim / duty cycle:** op 1 write to `<box>/distribution_box.<ch>.ratio` with an
  **int percent** (e.g. `33`). Raising `ratio` turns the channel on; switch off
  with `.state=false`.
- **ACK:** frame with matching `wopid`. Two observed codes:
  - `code=0` — explicit success, `data` echoes the set value.
  - `code=14` — accepted/queued; the server has forwarded the command to the
    device. The actual new state arrives shortly as an op=7 telemetry push.
    **Do not use op=2 read-back immediately after a write** — the server returns
    stale cached data before the device propagates the change. Subscribe to the
    topic and wait for the op=7 push instead.

## 5. Channel → user label map [confirmed]
Read from `<box>/userdata_str.config` (op 2 read; `data` is a JSON-encoded
string — sometimes double-encoded, parse up to twice). **The value is not a
flat `{channel: label}` map** — confirmed against a real capture
(`captures/*.har`):

```jsonc
{
  "distribution_box.dc_10a_1": {
    "name": "Bedroom Light",
    "channelEnable": true,
    "controlMode": 0,        // 0 = switch, 1 = dimmer
    "icon": "##ic_courtesy_light##",
    "showCurrent": false,
    "showPower": false
  },
  "distribution_box.ai_1": { "name": "Front", "channelEnable": true, "tankUsage": 0 },
  "distribution_box.ai_2": { "name": "--", "channelEnable": true, "tankUsage": 0 }
  // ...
}
```

Keys are **namespace-qualified** (`"<namespace>.<channel>"`, not bare
`"dc_10a_1"`) — strip the namespace prefix before matching against a
channel's `channel_key`. Values are an object (`ChannelConfig` in
`packages/core/src/types.ts`), not a bare string; the display name is
`value.name`. **An unconfigured channel reads back `name: "--"`** — treat
that placeholder as unset (fall back to the schema-derived default name),
not as a literal channel name. `controlMode` doubles as a second,
config-driven dimmable signal alongside the schema-derived one (writable
`ratio` sibling).

For this account, the resolved names are:

| channel | label | | channel | label |
|---|---|---|---|---|
| `dc_10a_1` | Bedroom Light | | `dc_20a_1` | Sockets |
| `dc_10a_2` | Reading Light | | `dc_20a_2` | Water Pump |
| `dc_10a_3` | Courtesy Light | | `dc_20a_3` | Power |
| `dc_10a_4` | Lounge Light | | `dc_20a_4` | Refrigerator |
| `dc_10a_5` | Outdoor Lights | | `relay_3` | Cooling Fan |
| `dc_10a_6` | Fans | | `ai_1` | Front (tank) |
| `dc_10a_7` | Kitchen Light | | `ai_3` | Rear (tank) |
| `dc_10a_8` | Media | | `ai_4` | Grey (tank) |
| | | | `temp_1`/`temp_2` | Ambient / Equipment |

Resolve names at runtime from `userdata_str.config`; the table above is just a
reference for this rig.

## 6. Telemetry registry [confirmed namespaces; full field list in captures]
~179 topics observed. Key namespaces and notable fields:

- `distribution_box` (54): per-channel `dc_10a_N.{state,power,ratio}`,
  `dc_20a_N.{state,power}`, `ai_N.{connected,mode,ratio}`.
- `tpms` (67): `tp_state_N.{pressure,temperature,battery_status,online,state}`,
  plus alarm thresholds.
- `shunt` (4): `main_battery_soc`, `main_battery_voltage`, `main_battery_current`,
  `battery_effective_cap`.
- `pv_input` (3): `charging_power`, `current`, `voltage`.
- `charger` (2): `charging_current`, `charging_power`.
- `ac_input` / `ac_output`, `battery_input`, `start_battery`.
- settings/meta: `gwmConfig.socRule`, `charge_tips.*`, `thing.{pid,sku,sw_ver,title,alarms}`,
  `version_ctrl.new_version`, `customAlarm.alarmList`.
- RPC: `gwm.{get_product,get_model,devs,dev_registered}`.

The static list above is a **reference snapshot only**. The protocol is fully
self-describing (see §7) — the canonical registry is discovered at runtime, and
any hardcoded table should exist only as an offline fallback.

---

## 7. Self-describing model discovery — the canonical path [confirmed]

The gateway publishes its own schema. Three RPCs (all on `1/...`, op 6) let a
client configure itself for *any* rig without hardcoding device types, channel
lists, units, or which fields are controllable.

### 7.1 `gwm.devs` — device inventory [confirmed two-step]
Call **two** sequential RPCs on `1/gwm.devs`:
1. `{dids:[<gatewayDid>]}` — registers the gateway into the RTM session
   (response has `"session":true`). Skipping this causes a `code=6` on step 2.
2. `{gatewayId:<gatewayDid>}` — returns child devices, each with `did_str`,
   `pid`, `sku`, `online`, `text` (name), `nodeType`, `typeId`.

⚠️ DIDs are int64 — send as bare JSON numbers. JavaScript `Number()` loses
precision (`227162568538456065 → 227162568538456060`); use BigInt + a custom
`stringify()` that emits BigInt as raw JSON numbers.

### 7.2 `gwm.get_product` — a device's capability namespaces
`{name: <pid>}` → `{ models: string[], model_ext: [{name, mid, addr}], pid,
nodeType, typeId, text, protocol }`. `models` is the list of namespaces the
product exposes. **A device's role IS its namespace set** — no SKU matching:
- `smartDistributionBox` → `[thing, distribution_box, customAlarm, userdata_str, driving_mode]`
- inverter `000F003C` → `[thing, pv_input, charger, charge_params, ac_input, ac_output, ac_load_driver, battery_input, inverter_state, …]`
- MPPT `000E002E` → `[thing, pv_input, charger, charger_params, charger_history, …]`
- `00340003` → `[thing, tpms]`

### 7.3 `gwm.get_model` — the field schema for a namespace
`{name: <namespace>}` → `{ name, mid, alarms[], inherit?, sps[] }`. Each entry in
`sps` describes one field ("sp"):

| key | meaning |
|---|---|
| `name` | stable field key (language-neutral — **use this**, not `text`) |
| `type` | `1` bool · `2` int · `3` float · `4` string · `5` array · `7` obj · `8` func (RPC method) · `9` series (time-series) |
| `unit` | display unit (`%`, `W`, `V`, `A`, `°C`, `kPa`) when present |
| `coef`, `precision` | scaled value = raw × `coef`, shown to `precision` dp |
| `min`, `max` | value bounds (e.g. `ratio` 0–100) — use for write validation |
| `options` | enum: `[{key, value}]` (e.g. tpms `state`, `socRule`, input `mode`) |
| **`ops`** | allowed operations — **not a freely-combinable bitmask**, see below. |
| `ref` | this field is an object of another model — resolve it (e.g. tpms `tp_state_N` → model `tpms_state`) |
| `inherit` | merge a parent model's `sps` (e.g. `dc_output_adjustable` inherits `dc_output_ext`) |
| `text`, `desc` | human label — **often Chinese**; treat as optional |

### 7.4 Everything you derive from the schema
- **Controllable** ⇔ the field's `ops` contains the **literal value `1`**.
  (Box `dc_*`/`relay_*` `.state` and dimmer `.ratio` are writable; `power`/
  `current` and tank `ai_*` `.ratio` are not — they fall out automatically.)
- **Dimmable** ⇔ the channel has a writable `ratio` (model `dc_output_adjustable`).
- **Units / scaling / type / enums / bounds** — all straight from the field entry.
- **Read vs subscribe** — `ops` membership of `2`/`5`/`7` (read) or `4`/`5`/`7` (subscribe).

⚠️ **`ops` is a small enum, not a bitmask to OR together.** Real `ops` values
are always one of `{1, 2, 4, 5, 7}` — `5` and `7` are *recognized composite
codes meaning "read + subscribe"*, not the sum of their binary digits. Despite
`5 == 4+1` and `7 == 4+2+1` in raw binary, **neither implies write on its
own** — write is contributed *only* by the literal code `1` being separately
present in the list. Confirmed against real captures: `inverter_history`'s
`Bat_Chg_Energy` reports `ops:[2,4,5,7]` (no literal `1`) and is genuinely
read-only, while `dc_output_ext.state` reports `ops:[1,2,4,5,7]` (literal `1`
present *alongside* `5`/`7`) and is genuinely writable. A client that derives
`writable` by OR-ing the raw integers together (`mask |= 7` sets bit 0 from
the literal value `7` alone) will misread every `[2,4,5,7]`-shaped reading as
writable — this bit the `ha-renogy-gateway` port twice before being traced
back to real capture data.

Worked examples from the box:
- `dc_output_ext`: `state` (bool, `ops [1,2,4,5,7]` → writable), `power`
  (int `W`, read-only), `current` (float `A`), `voltage` (float `V`).
- `dc_output_adjustable`: `inherit: dc_output_ext` + `ratio` (int `%`, min 0 max 100, writable).
- `relay`: `state` (bool, writable). `analog_input_r` (tanks): `ratio` read-only, `mode` with `options`.

### 7.5 What discovery does NOT give you
- **User-assigned names** ("Bedroom Light") — those live in `userdata_str.config`
  (op 2 read; **see §5 for the real payload shape** — namespace-qualified keys,
  object values with a `name` field, not a flat string map). Structure &
  capabilities from `get_model`; friendly names from `userdata_str.config`;
  fall back to the model's `name`/`text` if config is absent or the name is
  the `"--"` unset placeholder.
- **Control blacklist** — `driving_mode.ctrl_sp_blacklist` is a list of sp paths
  the device has disabled for control; a write validator should honour it.

### 7.6 Practicalities
`get_model` is ~25–30 calls to cover every namespace, but the schema is **static
per `pid` + firmware version**. Cache the resolved registry (DO storage / a file
keyed by pid+version) instead of re-fetching on every connect. Resolve `inherit`
and `ref` recursively before caching. The static `registry.ts` is now strictly a
fallback for offline/unknown-device cases.

**Cache scope & revalidation.** Cache per-product schemas in a shared namespace
(`product:<pid>`, `model:<namespace>`) so rigs with the same hardware reuse them,
and cache the assembled discovery as a **rig snapshot** keyed by the gateway
`did_str` (`rig:<rigId>`, with `sn` stored for display). Serve the snapshot
immediately for instant first paint, then revalidate from live in the background
and reconcile **device add / remove / capability change** against it (`diffRigs`).
Device online/offline is volatile — track it from live telemetry, not the
snapshot. Keying by rig leaves the door open to serving multiple rigs later (not
implemented).

### 7.7 Known schema inconsistencies — [confirmed via captures]
The schema is not perfectly self-consistent; these are confirmed real
deviations a client should defend against rather than assume away:

- **Some genuinely read-only fields carry the literal write code `1`
  anyway.** Confirmed in `inverter_history`: every lowercase `_today` daily
  accumulator (`bat_chg_ah_today`, `bat_dischg_ah_today`,
  `generat_energy_today`, `used_energy_today`, `load_consum_line_today`,
  `line_chg_energy_today`) reports `ops:[1,2,4,5,7]` despite being a counter
  no one would ever set — unlike their `_Total`/`Energy`-suffixed PascalCase
  siblings (`Bat_Chg_AH_Total`, `Bat_Chg_Energy`, ...), which correctly
  report `ops:[2,4,5,7]`. Also confirmed for TPMS `tp_state_N.{pressure,
  online,state}` on some rigs (not reproduced in this account's captures,
  but reported live). `voltage` is the one case the app's own curation
  already special-cases.
- **The same quantity appears under inconsistently-cased leaf names on the
  same device.** An inverter (RIV1230RCH-24S) reports both lowercase
  `voltage` and capitalised `battery_input.Voltage` for equivalent
  readings — match leaf-name overrides case-insensitively.
- **Some namespaces are never discovered live at all.** No capture ever
  shows `gwm.get_model` called for `ac_input`/`ac_output`/`battery_input`
  on the inverter — the app reads/subscribes known field paths
  (`ac_input.AC_input_Voltage`, `ac_input.AC_input_current`,
  `ac_input.AC_input_frequency`) directly without fetching the schema
  first, which is presumably why `registry.ts` hardcodes a fallback for
  this exact model.
- **Identically-named fields can disagree across namespaces.** `charger.
  desired_voltage`/`desired_current` correctly report `ops:[1,2,4,5,7]`
  (writable, a genuine setpoint), but `start_battery.desired_voltage`/
  `desired_current` report `ops:[2,4,5,7]` (no literal `1`) — the same
  conceptual setting, seemingly never marked writable for this sub-feature.
- **Units occasionally arrive in Chinese.** `charger.max_current` reports
  unit `安培` ("Ampere") rather than `A` on at least one rig — translate
  known Chinese unit strings rather than assuming ASCII.

---

## 8. Scenes — [confirmed REST; execution path partly inferred]

Scenes ("Away", "Home", "Standby", "Driving", "Cooling On/Off") are **cloud-stored
automations** managed through a dedicated **REST** API, *not* the RTM telemetry
namespaces. The RTM `scene` model is the **execution + live-feedback** side. Both
are scoped to the **gateway** device (the ONE Core `did`), discovered at runtime —
don't hardcode the example `did` below.

> ⚠️ Running a scene executes a batch of writes to physical circuits (loads,
> inverter, relays). Treat `scene.run` with the same control-safety care as a
> direct op-1 write: confirmation + logging, and explicit permission to test live.

### 8.1 REST CRUD — `gateway.renogy.com/api/v2/device/scene/*` [confirmed]
Standard authenticated REST (account `x-token`, same headers as §2). Responses are
`application/json` (`{code:"000000", msg, timestamp, data}`; `code "000000"` = ok).

- `GET /getUserScenes?gatewayDeviceId=<gwDid>&type=<1|2|3>`
  → `data: { sceneCount, scenes: Scene[] }`. The `type` filter:
  - **`2` = Manual** (user "Custom → Manual" scenes; run on demand)
  - **`3` = Auto** (condition-triggered; have an enable toggle)
  - **`1` = Favourites** (the starred subset; may overlap Manual/Auto)
  - The dashboard fetches `type=2` and `type=3`.
- `POST /updateScene` — create / edit / **toggle** a scene. Body is the full scene
  object (note: write-side uses `isManual` + nested `conditions[].conditions[]`,
  and the read-side `id` is echoed back). Toggling an Auto scene on/off is a
  `updateScene` with `isOpen` flipped.
- `GET /getBrokenScenes?gatewayDeviceId=<gwDid>&sceneId=<id>`
  → scenes whose operations/conditions reference a now-missing device
  (`{sceneName, brokenSceneId, brokenType}`). Health check; optional for the UI.

⚠️ `id`, `gatewayDeviceId`, `userId`, `deviceId` are int64 — the same float64
precision hazard as everywhere else. Read them from the raw response text /
preserve as strings; don't round-trip through `Number`.

### 8.2 Scene object shape [confirmed]
```jsonc
{
  "id": 2400162031240761,            // int64 scene id (use for scene.run)
  "sceneName": "Away",
  "imageUrl": "android.resource://…/ic_scene_away",  // icon; may be null or an https OSS url
  "isFavourite": true,
  "isOpen": true,                    // Auto enable toggle (true = armed)
  "isHide": false,
  "conditionType": 1,                // 1 = manual, 4 = condition/auto
  "repeatType": 2, "startTime": "00:00", "endTime": "23:59", "customWeek": "",
  "conditions": [                    // what triggers it
    { "conditionCode": "Manual", "conditionName": "Manual", "note": "Manually activated" }
    // auto example:
    // { "conditionCode": "distribution_box.temp_2.temperature", "triggerType": 3,
    //   "conditionType": 3, "conditionParameter": "35", "note": "Temp 2 is lower than 35℃" }
  ],
  "operations": [                    // what it does, in executeOrder
    { "operationCode": "distribution_box.dc_loads_ctrl",
      "operationType": 2,
      "operationParameter": "{\"loads\":1791,\"state\":false}",  // bitmask of DC channels + state
      "executeOrder": 0, "deviceId": 4623589794012005944, "note": "Loads Ctrl Turn off" },
    { "operationCode": "distribution_box.inverter_switch",
      "operationParameter": "false", "executeOrder": 1 }
  ],
  "deviceIds": [4623589794012005944]
}
```
Notes on `operations`:
- `operationParameter` is a **string** — either a JSON-encoded object (parse again,
  e.g. `dc_loads_ctrl` `{loads, state}`) or a bare scalar string (`"false"`, a percent).
- Observed `operationCode`s: `distribution_box.dc_loads_ctrl` (bulk multi-channel;
  `loads` is a 12-bit channel bitmask — `4095` = all 12), `distribution_box.dc_20a_N.state`,
  `distribution_box.relay_3.state`, `distribution_box.inverter_switch`. All
  `operationType: 2` in captures.
- We do **not** need to replay these ourselves if we execute via `scene.run` (§8.3).

### 8.3 RTM scene model — execution + feedback [model confirmed; run untested live]
`gwm.get_product` for the gateway lists a `scene` namespace; `gwm.get_model
{name:"scene"}` returns these members (all funcs are `type:8`, called op 6 on
`<gwDid>/scene.<fn>`):

| member | kind | input | meaning |
|---|---|---|---|
| `run` | func | `{sceneId}` | **execute a scene** (text 执行场景) — the Run button |
| `query` | func | `{id?}` | get scene list as a `scenes` JSON string (REST §8.1 is the path the app actually uses) |
| `save` / `del` | func | `{id, info}` / `{id}` | edit-add / delete (REST equivalents preferred) |
| `restore_scene` | func | `{sceneId}` | restore |
| `scene_trigger` | int, sub/read | — | id of the scene that **last fired** — drives active-scene highlight |
| `scene_trigger_ts` | series | — | trigger timestamps |
| `update_time_local` | int, sub/read/write | — | local scene-data version; **bumps when scenes change** — re-fetch on push |
| `log` / `log_ts` | string / series | — | scene execution log |

**Execution gap:** no live Run/execute was captured (the app only listed + edited
scenes, and passively subscribed to `scene.update_time_local` on connect). The
intended execution path is **op 6 `<gwDid>/scene.run {sceneId}`** — verify live
before relying on it. Fallback if `run` doesn't work: replay each `operation` as
op-1 writes using the `operationCode`/`operationParameter` above.

**Recommended client flow:** list via REST (`getUserScenes` type 2 + 3) → subscribe
`<gwDid>/scene.update_time_local` (re-fetch on change) and `<gwDid>/scene.scene_trigger`
(active-scene highlight) → Run via `scene.run` (confirmed in UI) → Auto enable
toggle via REST `updateScene` with `isOpen` flipped.
