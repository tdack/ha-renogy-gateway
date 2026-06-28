# Changelog

All notable changes to this project are documented in this file, generated
from the tagged release history.

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
