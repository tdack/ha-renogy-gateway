---
name: renogy-diagnostics-and-tooling
description: >-
  Load when you need to MEASURE integration behaviour instead of eyeballing
  it — interpret an HA diagnostics JSON dump, read renogy_gateway debug logs,
  mine HAR captures for schema evidence, audit curation drift between
  ha-renogy-gateway and the canonical renogy-gateway sibling, or check
  release consistency (manifest/CHANGELOG/tags/hacs.json) before tagging.
  Ships three tested stdlib scripts: curation_audit.py, release_check.py,
  diagnostics_summary.py.
---

# Renogy diagnostics and tooling

How to measure instead of eyeball: interpretation guides for the three
evidence sources (diagnostics dumps, debug logs, HAR captures) plus three
shipped scripts that turn "I think they match" into a diffable report.

**When NOT to use this skill:**
- Symptom triage ("entities unavailable", "write does nothing") → follow
  `renogy-debugging-playbook` first; come back here when it tells you to
  measure something.
- Evidence-handling methodology (what counts as proof, capture hygiene,
  how to cite captures) → `renogy-analysis-and-evidence`.
- What each curation constant MEANS and why it exists → `renogy-curation-and-flags`.

All repo paths below are repo-relative. Scripts take repo paths as CLI
arguments — never hardcode absolute paths. Scripts are plain Python 3.10+
stdlib: they run anywhere, no Home Assistant install, no third-party deps.

---

## Part 1 — Interpretation guides

### 1.1 HA diagnostics JSON

Source of truth: `custom_components/renogy_gateway/diagnostics.py`
(`async_get_config_entry_diagnostics`). The payload it returns is exactly:

```json
{
  "entry_data":    { "...config entry keys, sensitive ones redacted..." },
  "devices": [
    { "did_str": "...", "pid": "...", "sku": "...", "name": "...",
      "online": true, "field_count": 42, "writable_fields": 3,
      "subscribable_fields": 40 }
  ],
  "total_devices": 3,
  "total_fields": 160
}
```

HA's download button wraps this under a top-level `"data"` key (alongside
`"home_assistant"`, `"integration_manifest"`, ...). Both shapes are handled
by `scripts/diagnostics_summary.py`.

**Redaction.** Keys in `diagnostics.py`'s `_REDACT` set are replaced with
the literal string `**REDACTED**`: `email`, `password`, `access_token`,
`refresh_token`, `rtm_token`, `rtm_did`, `device_uuid`. Anything else in
`entry_data` (e.g. `gateway_id`, `gateway_name`) passes through as-is. If a
sensitive key appears un-redacted, the dump must not be shared —
`diagnostics_summary.py` flags this.

**Know what is NOT in the dump.** Per-device COUNTS only. No per-field
values, no field names, no `ctrl_sp_blacklist` contents, no record of which
phantom instance slots were dropped. Those need debug logs (§1.2) or live
inspection.

**Spotting common problems:**

| Observation in dump | Likely meaning | Next step |
|---|---|---|
| A device with `field_count: 0` | `gwm.get_product`/`gwm.get_model` RPC drops during discovery (retried 3× with backoff in `api/discovery.py::_rpc_with_retry`, but a first-ever setup can still fail through). On RE-discovery, `coordinator.py::_merge_devices` keeps the prior schema, so a zero here means the failure happened on initial setup. | Enable debug logging, look for `get_product(<pid>) failed` / `get_model(<ns>) failed`, reload the entry |
| `writable_fields` higher than expected for a device | Possible curation gap — a leaf the schema marks writable (`ops` ⊇ 1) that should be force-readonly or hidden | Run `scripts/curation_audit.py`; check the force-readonly axes against the sibling |
| Fewer entities than the rig has sensors (e.g. a wired tank missing) | The phantom-instance drop (`coordinator.py::_drop_phantom_instances`) removes any `ai_N`/`temp_N`/`tp_state_N` slot whose non-writable readings all seeded as `None`. Ask: is that right for this rig, or did the initial read burst fail for a real sensor? | Debug log: count `Initial read failed for <sp>` lines against `Subscribed to %d fields` |
| `online: false` on a child device | Device reported offline by the gateway itself — not an integration fault | Check the Renogy app / physical link |
| `total_fields` ≠ sum of `field_count` | Should never happen (both computed from the same `coordinator.devices`) — indicates a hand-edited or truncated dump | Get a fresh dump |

### 1.2 Reading debug logs

Logger namespace (from `manifest.json` `"loggers"`):
`custom_components.renogy_gateway`. Enable via the integration page's
"Enable debug logging", or:

```yaml
logger:
  logs:
    custom_components.renogy_gateway: debug
```

Key lines, quoted verbatim from source (format strings shown; `%s`/`%d`
are filled at runtime):

| Level | Line (verbatim) | Where | Interpretation |
|---|---|---|---|
| debug | `RTM connected (did=%s)` | `api/rtm.py` | WS upgrade + op-9/op-8 handshake succeeded |
| debug | `Discovered %d devices behind gateway %s` | `coordinator.py` | `gwm.devs` inventory complete; count includes the ONE Core itself |
| debug | `Initial read failed for %s` | `coordinator.py` | One field's seed read (op-2) failed. A few are normal; MANY on one instance prefix means that slot will be phantom-dropped |
| debug | `Subscribe failed for %s` | `coordinator.py` | op-4 subscribe failed for one sp — entity will rely on its seeded value only |
| debug | `Subscribed to %d fields` | `coordinator.py` | End of connect sequence; the live telemetry field count |
| debug | `Discovered %d scenes` | `coordinator.py` | REST scene fetch OK (scenes are optional polish) |
| debug | `gwm.devs step-1 failed; proceeding anyway` | `api/discovery.py` | Gateway self-registration RPC dropped — gateway's own device entry may be missing from `devices` |
| debug | `No namespaces for pid=%s, skipping device` | `api/discovery.py` | `get_product` returned empty → the device is skipped entirely (it will not even appear with zero fields) |
| debug | `get_product(%s) failed` / `get_model(%s) failed` | `api/discovery.py` | Schema RPC failed after 3 retries → device resolves with missing/zero fields |
| debug | `Could not read userdata_str.config for %s` | `api/discovery.py` | User channel labels unavailable → entities fall back to schema names ("Dc 10a 1" instead of "Bedroom Light") |
| debug | `Could not read ctrl_sp_blacklist for %s` | `api/discovery.py` | Blacklist unknown → writes will NOT be blocked by it (empty set assumed) |
| debug | `RPC %s timeout (attempt %d/%d)` | `api/rtm.py` | One RPC frame lost; rtm.py retries up to 3 |
| debug | `RTM reconnecting in %ds` | `coordinator.py` | Backoff loop running (2 s doubling to 30 s cap); entities are `unavailable` until it succeeds |
| info | `RTM reconnected successfully` | `coordinator.py` | Full reconnect incl. re-discovery + re-subscribe done |
| warning | `Write to %s returned unexpected code: %s` | `coordinator.py` | op-1 write was SENT and acked, but ack code ∉ {0, 14} — the device may not have applied it. Verify state before retrying |
| error | `Write to %s failed: %s` | `coordinator.py` | Write did not complete (RTM error/timeout) — raised to the HA service call |
| warning | `Run scene %s returned unexpected code: %s` | `coordinator.py` | Scene RPC acked with unexpected code |
| error | `Renogy connection error during login: %s` | `config_flow.py` | Setup-time REST failure (network / Renogy outage) |

### 1.3 Mining HAR captures (the evidence source of record)

Captures live in the sibling repo at `captures/` (renogy-gateway). If no
`.har` files are present in your working copy, these recipes are for when
captures exist locally — the folder is gitignored, so a fresh clone has
only its README.

**HARD WARNING: captures contain live credentials** — account tokens,
rtmToken JWTs, and the login request carries the password. Never quote a
raw frame, never commit capture content, never paste `x-token`/
`device-token` header values into a report. Extract only the specific
schema fact you need (names, `ops`, types, units).

Proxyman HAR structure: each entry has `_webSocketMessages[]`, whose
`data` is a JSON-encoded RTM frame. `gwm.get_model` responses arrive as
`op: 7` frames whose `sp` contains `get_model`. All recipes below were
test-run against a real capture on 2026-07-12.

List every namespace whose model appears in a capture:

```sh
jq -r '.log.entries[]._webSocketMessages[]?.data | fromjson?
  | select(.op==7 and ((.sp // "") | contains("get_model")))
  | .data | (if type=="string" then fromjson else . end) | .name' \
  captures/<file>.har | sort -u
```

Extract the `ops` array (and type/unit) for one field of one model —
the decisive evidence for any force-readonly argument:

```sh
jq -r --arg ns tpms_state --arg leaf pressure \
  '.log.entries[]._webSocketMessages[]?.data | fromjson?
  | select(.op==7 and ((.sp // "") | contains("get_model")))
  | .data | (if type=="string" then fromjson else . end)
  | select(.name==$ns) | .sps[] | select(.name==$leaf)
  | {name, type, ops, unit}' captures/<file>.har
```

Observed output (real capture): `{"name": "pressure", "type": 3,
"ops": [2, 4, 5, 7], "unit": null}` — note no literal `1`, so not
writable under `_parse_ops` rules (write comes ONLY from literal code 1).

Extract user channel labels from `userdata_str.config` (safe to quote —
they are user-assigned names, not credentials; `--` means unset):

```sh
jq -r '.log.entries[]._webSocketMessages[]?.data | fromjson?
  | select((.sp // "") | contains("userdata_str.config"))
  | .data | strings | fromjson? | fromjson? // . | to_entries[]?
  | "\(.key): \(.value.name)"' captures/<file>.har | sort -u
```

Python equivalent when `jq` is unavailable (same frame-walking shape):

```sh
python3 -c "
import json, sys
d = json.load(open(sys.argv[1]))
for e in d['log']['entries']:
    for m in e.get('_webSocketMessages') or []:
        try: j = json.loads(m.get('data', ''))
        except Exception: continue
        if j.get('op') == 7 and 'get_model' in str(j.get('sp', '')):
            inner = j['data']
            if isinstance(inner, str): inner = json.loads(inner)
            print(inner.get('name'))
" captures/<file>.har | sort -u
```

---

## Part 2 — Shipped scripts

All three live in `scripts/` next to this file, run on Python 3.10+ stdlib
only, and were test-run against the real repos on 2026-07-12.

### 2.1 `scripts/curation_audit.py` — curation drift report

The measurement backbone of the curation-parity campaign. Parses the HA
integration's curation constants exactly (Python `ast`) and the canonical
TS sibling's heuristically (regex + bracket matching), then prints a
sorted, diff-friendly side-by-side per axis.

```sh
python3 scripts/curation_audit.py <path-to-ha-renogy-gateway> <path-to-renogy-gateway>
```

Axes: `force_readonly_leaves`, `force_readonly_suffixes`,
`force_readonly_by_namespace`, `force_readonly_by_pid`, `hide_leaves`,
`diagnostic_patterns`, plus `skip_namespaces` as informational (the two
sets have intentionally different scopes — see below). Markers: `=` both,
`<` HA-only, `>` TS-only. Exit 0 = no drift on strict axes, 1 = drift,
2 = parse failure.

Observed output (real repos, 2026-07-12, trimmed to the drifting axes —
the four force-readonly axes and diagnostic_patterns reported zero drift):

```
== hide_leaves (const.py HIDE_LEAVES vs params.ts PARAM_HIDE_LEAF) ==
  = addr
  = alarmList
  ...
  < ai_count   (HA only)
  < dc_10a_count   (HA only)
  < dc_20a_count   (HA only)
  < dc_voltage_count   (HA only)
  < di_count   (HA only)
  < relay_count   (HA only)
  > ratio   (TS only)
  > state   (TS only)
  -- both=11 ha_only=6 ts_only=2

== skip_namespaces (...) [informational] ==
  ...
  > alternator   (TS only)
  > battery_temp_sensor   (TS only)
  ...
  -- both=17 ha_only=0 ts_only=6

TOTAL DRIFT (strict axes): 8 entries
```

**Interpreting drift:** not all drift is a bug — some entries are
intentional scope divergence between the two repos' constants. Exit-code
mechanics: `0` = no strict-axis drift; `1` = drift found (classify every
entry before acting — never blind-sync); `2` = parse failure (fix the
instrument first, trust nothing it printed). The classification of each
drift entry (intentional-divergence fences, port candidates, rationale) is
owned by `renogy-curation-parity-campaign` Phase 2 — do not re-derive
verdicts here.

**Parsing limits (be honest):** the TS side is regex, not a parser. It
assumes flat literal `new Set([...])` / `[...]` / `Record` initialisers and
will silently miss entries built by spread, computed keys, or brackets
inside string values. If a TS constant is refactored into a non-literal
form, the script exits 2 (constant not found) rather than lying — but a
partially-matched literal is not detectable, so spot-check the counts
against the source when an axis looks suspiciously empty. The Python side
(ast) is exact. Comparison is case-insensitive on the force-readonly axes
(both implementations match case-insensitively) and case-sensitive on
patterns.

### 2.2 `scripts/release_check.py` — release consistency

Enforces the repo's release rule (CLAUDE.md: changelog entry before
version bump and tag). Read-only git (`git -C <repo> tag --list` only).

```sh
python3 scripts/release_check.py <path-to-ha-renogy-gateway>
```

Checks: manifest.json parses + semver version; hacs.json parses;
`## [<manifest version>]` heading exists in CHANGELOG.md; newest changelog
version >= newest `vX.Y.Z` tag; WARN if the manifest version is already
tagged. Exit 0 = pass (warnings allowed), 1 = a FAIL, 2 = bad usage.

Observed output (real repo, 2026-07-12):

```
PASS  manifest.json parses; version 0.5.1
PASS  hacs.json parses
PASS  CHANGELOG.md has an entry for 0.5.1
PASS  newest changelog entry 0.5.1 >= newest tag v0.5.1
WARN  manifest version 0.5.1 is already tagged (v0.5.1). Fine post-release; if preparing a release, bump the version.

result: 0 failed, 1 warning(s)
```

| Result | Meaning |
|---|---|
| All PASS + the "already tagged" WARN | Normal steady state between releases |
| That WARN while you are preparing a release | You forgot to bump `manifest.json` — bump it (and add the changelog entry) before tagging |
| FAIL "CHANGELOG.md has NO entry for manifest version" | Version was bumped without the changelog entry — violates the repo rule; write the entry before tagging |
| FAIL "newest changelog entry ... OLDER than newest tag" | A tag was pushed without its changelog entry — repair the changelog retroactively |

Limits: only `vX.Y.Z` tags and `## [x.y.z]` headings are recognised; it
does not verify the changelog was committed *before* the bump commit
(ordering within history is out of scope), nor push state on the remote.

### 2.3 `scripts/diagnostics_summary.py` — rig summary from a diagnostics dump

```sh
python3 scripts/diagnostics_summary.py <downloaded-diagnostics.json>
```

Accepts either the raw payload or HA's `"data"`-wrapped download. Prints a
per-device table (name, did_str, pid, sku, online, field/writable/
subscribable counts), the `entry_data` keys, and flags: zero-field devices,
offline devices, un-redacted sensitive keys, totals mismatch. Exit 0 =
summarised, 2 = unrecognised structure.

Sample output (SYNTHETIC input — constructed to match `diagnostics.py`'s
exact emitted structure; no real dump was available in the sandbox):

```
== rig summary ==
devices: 3   fields: 160

name                         did_str      pid        sku                online  fields  writ  subs
--------------------------------------------------------------------------------------------------
ONE Core                     12345678     003F0000   RMTG-MON1          True        42     3    40
Inverter                     23456789     000F003C   RIV1230RCH-24S     True       118    14   110
MPPT Charger                 34567890     00030016   RCC60REGO-G2       False        0     0     0

entry_data keys: access_token, device_uuid, email, gateway_id, gateway_name, refresh_token, rtm_did, rtm_token

== flags ==
  ! MPPT Charger (34567890): ZERO fields — schema resolution failed (get_product/get_model RPC drops); expect no entities for this device
  ! MPPT Charger (34567890): reported offline
```

Interpret flags with the table in §1.1. Limits: the dump carries counts
only, so the script cannot name missing fields, list blacklisted sps, or
show values — the note it prints says so; go to debug logs for those.

---

## Provenance and maintenance

- Authored 2026-07-12 against ha-renogy-gateway v0.5.1 (tag v0.5.1) and
  the renogy-gateway sibling at the same date. Every quoted structure,
  log line, and constant name was read from source, and every command and
  script was executed against the real repos (curation_audit.py and
  release_check.py on real trees; diagnostics_summary.py on a synthetic
  dump matching diagnostics.py's emitted shape; jq recipes on a real HAR).
- Grounding files — re-verify against these when they change:
  `custom_components/renogy_gateway/diagnostics.py`, `coordinator.py`,
  `const.py`, `api/discovery.py`, `api/rtm.py`, `manifest.json`;
  sibling `packages/core/src/discovery.ts`, `packages/core/src/params.ts`,
  `apps/hass-bridge/src/filter.ts`.
- Fragile couplings: `curation_audit.py` hardcodes the constant NAMES and
  file paths above — renaming a constant or moving a file breaks it (it
  fails loudly, exit 2). `diagnostics_summary.py` mirrors `_REDACT` and
  the payload keys — update both if `diagnostics.py` changes. The log-line
  table quotes format strings verbatim — re-grep after refactors:
  `grep -rn "_LOGGER\." custom_components/renogy_gateway/`.
- Drift classification lives in `renogy-curation-parity-campaign` (Phase 2);
  if the campaign closes the `*_count` gap or restructures the hide sets,
  that skill's tables get updated, not this file.
