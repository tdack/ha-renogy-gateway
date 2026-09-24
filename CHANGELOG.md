# Changelog

All notable changes to this project are documented in this file, generated
from the tagged release history.

## [0.5.3] - 2026-09-24

- Harden write validation, ported from the sibling `renogy-gateway` core's
  `validateWrite` (2026-09-24). Number fields now refuse `NaN` and
  `±Infinity` — `NaN` fails every bounds comparison, so it slipped past the
  min/max check, and Home Assistant's number service coerces the string
  `"nan"` into one. Integer fields refuse values beyond the JS safe-integer
  range the canonical core accepts. Fields whose *schema* declares `options`
  now accept only one of those keys, so an in-range but undefined mode code is
  refused; booleans are exempt, and curated fallback options (e.g.
  `battery_type`'s) remain presentation only and are not enforced.
- Add a regression test pinning that user-assigned channel names are shown
  verbatim, even when they look like a schema leaf ("Power") or aren't ASCII.
  The sibling's dashboard and MQTT bridge had this bug; this integration
  never did.

## [0.5.2] - 2026-08-30

Reliability fixes in the auth and connection layers, found by porting the
review recently done on the sibling `renogy-gateway` project. No new entities
and no config changes — existing installs pick these up transparently.

- Fix the 401/999 retry never actually retrying with a new token. The retry
  called `ensure_fresh()`, which only rotates when the access token's own
  `exp` claim says it is stale — so when the server rejected a token that
  still looked fresh locally (revocation, clock skew), it was a no-op and the
  retry re-sent the very token that had just failed. It now forces a rotation.
- Serialise token rotation behind a lock. Refresh tokens rotate and the server
  kills the old one on first use, so two concurrent callers could each spend
  the same token; whichever response landed last was persisted, which could
  store a **dead** token and leave the integration unable to authenticate until
  it was reconfigured. Home Assistant runs entity handlers concurrently
  (`PARALLEL_UPDATES = 0`), so this was reachable.
- Report a rejected login properly. The API answers HTTP 200 with a failure
  envelope for a bad password, so reading `data` blind raised `KeyError` and
  the config flow showed "unknown error" instead of "invalid credentials" —
  and never offered reauth. Login, token refresh, RTM registration and RTM
  token rotation now all validate the envelope and surface the server's own
  message. A partial response can no longer persist a half-formed token pair.
- Survive a `ping` frame arriving before the RTM connect-ack. The gateway sends
  bare `ping` text frames unprompted; `json.loads("ping")` raised
  `JSONDecodeError`, which is not an `aiohttp.ClientError`, so it escaped as an
  unexpected exception rather than a clean connection error. The connect-ack
  read now skips pings (answering them), tolerates stray frames, and matches
  the ack on `sop: 9` — `op: 8` is the *generic* ack, not the connect-ack.
- Log write and scene failures with `logging.exception`, so the traceback is
  captured rather than just the message.
- Add ruff to CI (lint + format check) and 17 regression tests, each confirmed
  to fail against the code before these fixes.

## [0.5.1] - 2026-07-06

- Fix the inverter's `battery_type` field (pid `000F003C`) surfacing as a
  writable select whose curated 0-5 options can't represent its actual
  value (14) — the schema's own description says battery type on
  REGO-family inverters is fixed by the product, not user-settable.
  Force it read-only for that pid specifically; genuine MPPT/DC-DC
  chargers are unaffected.
- Add a regression test confirming a multi-namespace device (e.g. the
  inverter's `ac_input`/`ac_output`/`charger` fields) is grouped under a
  single HA device, not split across several.

## [0.5.0] - 2026-06-28

- Retry `gwm.get_product`/`gwm.get_model`/`gwm.devs` RPCs with backoff so a
  single frame dropped in the connect-time burst no longer permanently
  leaves a device with no schema.
- Surface the gateway itself (the ONE Core) as a device, captured from the
  `gwm.devs` step-1 registration response and deduped against the child
  device list.
- Non-destructively merge devices on rediscovery (e.g. after a reconnect):
  if a device resolves to zero fields on a flaky pass, keep its prior
  schema instead of tearing down all its entities; genuinely removed
  devices are still dropped.
- Validate writes against the field's schema (existence, writability,
  type, min/max bounds) before issuing the control frame, instead of only
  enforcing the control blacklist.
- Port curated English labels, curated enum options (e.g. battery type),
  and Chinese-to-English option-label translation from the canonical
  `renogy-gateway` core, so entity names and dropdown options no longer
  leak raw schema field names or untranslated Chinese labels.

## [0.4.0] - 2026-06-28

- Wire the RTM reader's unexpected-disconnect signal to the coordinator's
  auto-reconnect logic — entities now correctly flip to `unavailable` on a
  dropped WebSocket and recover automatically once it reconnects (previously
  `schedule_reconnect()` was never invoked, so a dropped connection was
  permanent until HA reloaded the integration).
- Use `asyncio.get_running_loop()` instead of the deprecated
  `asyncio.get_event_loop()` in the RTM client's RPC call path.
- Stop persisting the account password in the config entry; existing entries
  are migrated to drop any previously-stored password.
- Redact the account email in downloadable diagnostics output.
- Dedupe concurrent `gwm.get_model` RPCs issued during device discovery.
- CI: don't run the Validate workflow on tag pushes (GitHub API ref
  propagation race).

## [0.3.0] - 2026-06-27

- Surface metadata-only devices (e.g. "Vision") that have no entities of
  their own, and add firmware version / connection type metadata.
- Bundle the protocol documentation locally instead of linking out.
- Add a regression test for tank ratio/connected classification.

## [0.2.9] - 2026-06-27

- Fix user-assigned channel labels never being applied to entities.

## [0.2.8] - 2026-06-27

- Audit the full schema dump from real captures; hide internal channel-count
  fields and fix the Chinese (zh) unit string translation.

## [0.2.7] - 2026-06-27

- Fix incorrect `ops=7` decomposition, make leaf-name overrides
  case-insensitive, and force `_today` daily counters read-only.

## [0.2.6] - 2026-06-27

- Normalise milli-prefixed units (mV, mA, ...) and cap displayed precision.

## [0.2.5] - 2026-06-27

- Fix TPMS pressure/online/state misclassification and drop ghost
  (unbound) instance slots.

## [0.2.4] - 2026-06-25

- Fix the root cause of incorrect `ops` parsing and drop the path-pattern
  band-aid that had been working around it.

## [0.2.3] - 2026-06-25

- Force well-known telemetry paths to be treated as read-only.

## [0.2.2] - 2026-06-25

- Use Renogy's official brand icon/logo; fix codeowners.

## [0.2.1] - 2026-06-25

- Add an integration icon (borrowed from the renogy-gateway dashboard
  favicon); fix a stale repo owner in manifest URLs.

## [0.2.0] - 2026-06-25

- Initial standalone release: import the `renogy_gateway` integration source
  from ha-core, adapt the manifest for HACS distribution, port the test
  suite to `pytest-homeassistant-custom-component`, and add CI
  (hassfest/HACS validation, pytest).
- Narrow the discovery namespace skip-list to match dashboard curation.
- Add an enum sensor entity for read-only options fields.
- Stop requiring schema min/max bounds to surface a Number entity.
- Move status/alarm/firmware fields into the Diagnostic entity category.
- Add scene support: a Manual-scene run button and an Auto-scene enable
  switch.
